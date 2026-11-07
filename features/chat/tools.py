# features/chat/tools.py
"""
features/chat/tools.py — The database lookups the agent may ask for.

WHAT THIS FILE DOES
    Holds the seven lookups the LLM can request, plus the descriptions it reads to
    choose between them. The LLM never writes SQL and never computes a number: it
    names a lookup and its arguments, THIS FILE runs it on SQLite / ChromaDB, and the
    result goes back to the model. All numbers come from the same code the API uses
    (features/metrics.py, features/daos/service.py, features/chat/context.py).

        find_proposals    title words -> proposal ids        (a question names a proposal)
        list_proposals    rank proposals: most voters / newest / closest, one DAO or all
        dao_stats         per-DAO numbers: proposals held, forum coverage, silence ratio
        proposal_details  one proposal: result, voters, forum posters, top-4 share
        top_voters        the largest voters on a proposal and their ballots
        person            a forum user / ENS name / wallet: wallet link, vote, posts
        search_forum      vector search over forum posts and proposal text (opinions, reasons)
                          each forum passage carries its author's wallet and vote

    Every lookup returns a plain Python object. Two views of it exist:
      * the RAW result goes into the evidence list (features/chat/agent.py), so the
        writer (features/chat/prompt.py) sees all of it;
      * fetcher_view() gives the agent a SHORTER text, to keep its conversation small.

WHERE IT SITS
    features/chat/agent.py  --run_tool-->  THIS FILE  -->  SQLite (features/chat/context.py,
                                                            features/metrics.py)
                                                       -->  ChromaDB (features/chat/retrieval.py)
    TOOLS (below) is the list of descriptions sent to the LLM with every agent call.

INPUTS
    conn - SQLite connection opened by agent.gather_evidence. Every other argument is
           chosen by the MODEL in its tool call, except the defaults run_tool fills in
           (the proposal the user selected, the number of passages requested).
"""

import datetime
import inspect
import json
import re

from config.curated_daos import CURATED_DAOS
from features.chat.context import enrich_chunks, proposal_facts
from features.chat.retrieval import retrieve
from features.daos.service import compute_dao_stats
from features.identity.common import verified_ens_name
from features.metrics import choice_text, decode_choice, winning_choice, winning_share_pct

# How far (cosine distance, lower = closer in meaning) a passage may be from the query. Measured on
# real data: a descriptive sentence lands at 0.44-0.58, one keyword at 0.72-0.95. Inside one proposal
# or one author's posts the nearest passages are meaningful even when not very close; across all
# proposals a weak match is only noise.
MAX_DISTANCE_ANYWHERE = 0.7
MAX_DISTANCE_ONE_PROPOSAL = 0.85
MAX_DISTANCE_ONE_AUTHOR = 1.0
MAX_RESULT_CHARS = 3500   # one result is cut to this (free LLM tiers limit tokens per minute)
POST_CHARS = 700          # forum text per post inside person()
VIEW_CHARS = 300          # passage text the agent sees (the writer gets the full passage)
DAO_NAMES = {d["id"]: d["name"] for d in CURATED_DAOS}


# ── Small helpers ─────────────────────────────────────────────────────────────

def resolve_dao(text: str | None) -> str | None:
    """
    The space id of the curated DAO that `text` names, or None.
    'arbitrum' / 'Arbitrum DAO' / 'op collective' / 'arbitrumfoundation.eth' -> its space id.
    Matches the id, its first part, the name and the aliases (config/curated_daos.py) as
    whole words, so "tokens and lenses" does not match ENS.

    Parameter (where it comes from): the model's `dao` argument in a tool call.
    """
    text = (text or "").lower().strip()
    if text in DAO_NAMES:
        return text
    found = []
    for dao in CURATED_DAOS:
        words = {dao["id"], dao["id"].split(".")[0], dao["name"].lower(), *dao.get("aliases", [])}
        positions = [m.start() for w in words for m in re.finditer(rf"(?<![\w.]){re.escape(w)}(?![\w])", text)]
        if positions:
            found.append((min(positions), dao["id"]))
    return min(found)[1] if found else None


def _unknown_dao(dao: str) -> dict:
    return {"error": f"Unknown DAO '{dao}'. Known DAOs: {', '.join(DAO_NAMES.values())}."}


def _date(ts: int | None) -> str | None:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d") if ts else None


def _result(r) -> str | None:
    """'winner: For 91.7%' for a closed vote, 'leading: For 93.8%' for an open one."""
    choice = winning_choice(r["choices_json"], r["scores_json"])
    share = winning_share_pct(r["scores_json"], r["scores_total"])
    if choice is None or share is None:
        return None
    return f"{'winner' if r['state'] == 'closed' else 'leading'}: {choice} {share}%"


def _clip(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + " [...]"


def _bounded(value, low: int, high: int) -> int:
    return max(low, min(int(value), high))


# ── The lookups ───────────────────────────────────────────────────────────────

def find_proposals(conn, words: str, dao: str | None = None) -> list | dict:
    """Proposals whose title contains the most of these words (best match first, max 5)."""
    space = resolve_dao(dao)
    if dao and not space:
        return _unknown_dao(dao)
    terms = [w for w in words.lower().replace('"', " ").split() if len(w) > 1]
    rows = conn.execute("SELECT id, space_id, title, state, votes_count FROM proposals").fetchall()
    scored = [(sum(t in (r["title"] or "").lower() for t in terms), r)
              for r in rows if not space or r["space_id"] == space]
    scored = sorted((s for s in scored if s[0]), key=lambda s: -s[0])[:5]
    if not scored:
        return {"error": "No proposal title contains those words."}
    return [{"proposal_id": r["id"], "title": r["title"], "dao": DAO_NAMES.get(r["space_id"]),
             "state": r["state"], "voters": r["votes_count"],
             "title_words_matched": f"{score} of {len(terms)}"} for score, r in scored]


def list_proposals(conn, order_by: str = "voters", dao: str | None = None, limit: int = 5) -> dict:
    """Proposals of one DAO or of all DAOs, ranked by voters, newest first, or closest result."""
    space = resolve_dao(dao)
    if dao and not space:
        return _unknown_dao(dao)
    rows = conn.execute(
        "SELECT id, space_id, title, state, votes_count, created_ts, end_ts, choices_json, "
        "scores_json, scores_total FROM proposals" + (" WHERE space_id = ?" if space else ""),
        (space,) if space else ()).fetchall()
    held = len(rows)
    if order_by == "newest":
        rows.sort(key=lambda r: r["created_ts"] or 0, reverse=True)
        order = "newest first"
    elif order_by == "closest":
        # in a nine-candidate election an 18% winner is normal, so only 2-3 option votes count
        rows = [r for r in rows if r["state"] == "closed" and r["choices_json"]
                and len(json.loads(r["choices_json"])) <= 3
                and winning_share_pct(r["scores_json"], r["scores_total"]) is not None]
        rows.sort(key=lambda r: winning_share_pct(r["scores_json"], r["scores_total"]))
        order = "smallest winning share first (closed votes with two or three options)"
    else:
        rows.sort(key=lambda r: r["votes_count"] or 0, reverse=True)
        order = "most voters first"
    return {
        "scope": f"all {held} proposals we hold for {DAO_NAMES[space] if space else 'all 5 DAOs'} "
                 "(the most recent ones of each DAO, not their full history)",
        "order": order,
        "proposals": [{"proposal_id": r["id"], "dao": DAO_NAMES.get(r["space_id"]), "title": r["title"],
                       "state": r["state"], "voters": r["votes_count"], "voting_ends": _date(r["end_ts"]),
                       "result": _result(r)}
                      for r in rows[:_bounded(limit, 1, 10)]],
    }


def dao_stats(conn, dao: str | None = None) -> dict:
    """Numbers per DAO (all 5 when dao is empty): proposals held, forum coverage, silence ratio."""
    space = resolve_dao(dao)
    if dao and not space:
        return _unknown_dao(dao)
    return {
        "silence_ratio_means": "forum posters / voters, in % (low = few voters ever post on the forum)",
        "daos": [{"dao": DAO_NAMES[s], **compute_dao_stats(conn, s)} for s in ([space] if space else DAO_NAMES)],
    }


def proposal_details(conn, proposal_id: str) -> dict:
    """One proposal's result, voters, forum posters, silence ratio and top-4 voting-power share."""
    facts = proposal_facts(conn, proposal_id)
    if not facts:
        return {"error": "No proposal with that id; use find_proposals."}
    return {**facts, "silence_ratio_means": "forum posters / voters, in %"}


def top_voters(conn, proposal_id: str, n: int = 5) -> dict:
    """The n voters with the most voting power on a proposal, with their ballots and identities."""
    p = conn.execute("SELECT title, choices_json, votes_count FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if not p:
        return {"error": "No proposal with that id; use find_proposals."}
    choices = json.loads(p["choices_json"]) if p["choices_json"] else []
    total_vp = conn.execute("SELECT SUM(vp) FROM votes WHERE proposal_id = ?", (proposal_id,)).fetchone()[0] or 0
    voters = []
    for rank, v in enumerate(conn.execute(
            "SELECT voter, vp, choice_json FROM votes WHERE proposal_id = ? ORDER BY vp DESC LIMIT ?",
            (proposal_id, _bounded(n, 1, 10))), 1):
        user = conn.execute("SELECT forum_username FROM resolved_identities WHERE lower(wallet_address) = ?",
                            (v["voter"].lower(),)).fetchone()
        voters.append({"rank": rank, "wallet": v["voter"], "ens_name": verified_ens_name(conn, v["voter"]),
                       "forum_username": user[0] if user else None, "voting_power": round(v["vp"], 2),
                       "share_of_voting_power_pct": round(100 * v["vp"] / total_vp, 1) if total_vp else None,
                       "ballot": choice_text(decode_choice(v["choice_json"], choices))})
    return {"proposal": p["title"], "total_voters": p["votes_count"],
            "ballot_means": "how the voter split their voting power: a number after a choice is the part of "
                            "their power given to it; 'For' alone means all of it",
            "top_voters": voters}


def person(conn, name: str, proposal_id: str | None = None) -> dict:
    """A forum username, ENS name or wallet: who it is, and (for one proposal) their vote and posts."""
    key = name.strip().lstrip("@").lower()
    ident = conn.execute("SELECT forum_username, wallet_address, confidence_level FROM resolved_identities "
                         "WHERE forum_username = ?", (key,)).fetchone()
    wallet = ident["wallet_address"] if ident else None
    if not wallet:                                    # not a forum username: try a wallet or an ENS name
        if key.startswith("0x"):
            wallet = key
        else:
            ens = conn.execute("SELECT wallet_address FROM wallet_ens WHERE lower(ens_name) IN (?, ?)",
                               (key, key + ".eth")).fetchone()
            wallet = ens[0] if ens else None
        if wallet:
            ident = conn.execute("SELECT forum_username, wallet_address, confidence_level FROM resolved_identities "
                                 "WHERE lower(wallet_address) = ?", (wallet.lower(),)).fetchone()
    username = ident["forum_username"] if ident else key
    posted = conn.execute("SELECT username FROM forum_posts WHERE lower(username) = ? LIMIT 1", (username,)).fetchone()
    if not wallet and not posted:
        return {"error": f"No forum user, ENS name or wallet called '{name}' in our data."}

    out = {"forum_username": posted[0] if posted else None, "wallet": wallet,
           "ens_name": verified_ens_name(conn, wallet) if wallet else None,
           "wallet_link_confidence": ident["confidence_level"] if ident else None}
    if proposal_id:
        vote = conn.execute(
            "SELECT v.vp, v.choice_json, p.choices_json FROM votes v JOIN proposals p ON p.id = v.proposal_id "
            "WHERE v.proposal_id = ? AND lower(v.voter) = ?", (proposal_id, (wallet or "").lower())).fetchone()
        out["vote_on_this_proposal"] = (
            {"ballot": choice_text(decode_choice(vote["choice_json"], json.loads(vote["choices_json"] or "[]"))),
             "voting_power": round(vote["vp"], 2)} if vote else "no vote from this wallet in our data")
        out["posts_on_this_proposal"] = [
            {"post_number": r["post_number"], "text": _clip(r["content"], POST_CHARS)}
            for r in conn.execute("SELECT post_number, content FROM forum_posts WHERE proposal_id = ? "
                                  "AND lower(username) = ? ORDER BY post_number LIMIT 3", (proposal_id, username))]
    else:
        out["votes_in_our_data"] = conn.execute("SELECT COUNT(*) FROM votes WHERE lower(voter) = ?",
                                                ((wallet or "").lower(),)).fetchone()[0]
        out["proposals_posted_on"] = [r[0] for r in conn.execute(
            "SELECT DISTINCT p.title FROM forum_posts f JOIN proposals p ON p.id = f.proposal_id "
            "WHERE lower(f.username) = ? LIMIT 5", (username,))]
    return out


def search_forum(conn, query: str, proposal_id: str | None = None, author: str | None = None, n: int = 5,
                 source_type: str | None = None, dao: str | None = None) -> dict:
    """
    Passages (forum posts and proposal text) closest in meaning to the query, optionally
    limited to one proposal, one DAO, one author and/or one kind of text ("proposal_body" = the
    proposal's own text, "forum_post"). A DAO limits the search to the passages of that DAO's
    proposals (the index has no DAO field on forum chunks, so we filter on the DAO's proposal ids);
    it is ignored when a proposal is given, since the proposal is narrower. Returns {"chunks": [...]}: the chunks of
    features/chat/retrieval.py, each with "sql" (the author's wallet, link confidence, vote
    and voting power on that proposal) and "proposal_title".
    """
    filters = [{"proposal_id": proposal_id}] if proposal_id else []
    if dao and not proposal_id:
        space = resolve_dao(dao)
        if not space:
            return {"error": f"'{dao}' is not one of our DAOs ({', '.join(d['name'] for d in CURATED_DAOS)})."}
        ids = [r[0] for r in conn.execute("SELECT id FROM proposals WHERE space_id = ?", (space,))]
        if not ids:
            return {"chunks": [], "note": f"we hold no proposals of {DAO_NAMES[space]}"}
        filters.append({"proposal_id": {"$in": ids}})
    if source_type:
        filters.append({"source_type": source_type})
    if author:
        row = conn.execute("SELECT username FROM forum_posts WHERE lower(username) = ? LIMIT 1",
                           (author.strip().lstrip("@").lower(),)).fetchone()
        if not row:
            return {"error": f"No forum posts by '{author}' in our data."}
        filters.append({"author": row[0]})       # the index stores the username's original spelling
    where = filters[0] if len(filters) == 1 else ({"$and": filters} if filters else None)
    max_distance = (MAX_DISTANCE_ONE_AUTHOR if author else
                    MAX_DISTANCE_ONE_PROPOSAL if proposal_id else MAX_DISTANCE_ANYWHERE)
    chunks = retrieve(query, n_results=_bounded(n, 1, 8), where=where, max_distance=max_distance)
    enrich_chunks(conn, chunks)
    titles = {}
    for c in chunks:
        pid = c["metadata"].get("proposal_id")
        if pid not in titles:
            row = conn.execute("SELECT title FROM proposals WHERE id = ?", (pid,)).fetchone()
            titles[pid] = row[0] if row else None
        c["proposal_title"] = titles[pid]
    return {"chunks": chunks} if chunks else {"chunks": [], "note": "nothing close enough to the query"}


FUNCTIONS = {f.__name__: f for f in (find_proposals, list_proposals, dao_stats, proposal_details,
                                     top_voters, person, search_forum)}


# ── What the LLM reads ────────────────────────────────────────────────────────

def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """One tool description in the format Groq/OpenAI expect."""
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


_DAO_ARG = {"type": "string", "description": "DAO name, e.g. 'arbitrum', 'aave', 'optimism', 'uniswap', 'ens'. "
                                             "Leave out for all DAOs."}
_PID_ARG = {"type": "string", "description": "Snapshot proposal id (0x...), from find_proposals or list_proposals."}

# The descriptions ARE the instructions: a vague one here means the model picks the wrong tool.
TOOLS = [
    _tool("find_proposals", "Find proposals by words from their title. Use it whenever the question names "
          "a proposal, to get its proposal_id.",
          {"words": {"type": "string", "description": "Words from the proposal title."}, "dao": _DAO_ARG},
          ["words"]),
    _tool("list_proposals", "Rank proposals of one DAO or of ALL DAOs: by number of voters, newest first, "
          "or closest result. Use for 'most voted', 'top', 'recent', 'latest', 'closest', 'most contested'.",
          {"order_by": {"type": "string", "enum": ["voters", "newest", "closest"]}, "dao": _DAO_ARG,
           "limit": {"type": "integer", "description": "How many (1-10, default 5)."}},
          ["order_by"]),
    _tool("dao_stats", "Per-DAO numbers: proposals we hold, forum coverage %, average silence ratio "
          "(forum posters / voters), average winning share. Leave dao out to compare all DAOs.",
          {"dao": _DAO_ARG}, []),
    _tool("proposal_details", "One proposal's result per choice, winner, number of voters (total_voters), "
          "number of different people who posted on its forum thread (forum_posters), silence ratio and the "
          "voting-power share of its top 4 voters. Use it for any COUNT of voters or posters.",
          {"proposal_id": _PID_ARG}, ["proposal_id"]),
    _tool("top_voters", "The voters with the most voting power on one proposal: wallet, ENS name, forum "
          "username, voting power and their full ballot.",
          {"proposal_id": _PID_ARG, "n": {"type": "integer", "description": "How many (1-10, default 5)."}},
          ["proposal_id"]),
    _tool("person", "Look up one person by forum username, ENS name or wallet: their linked wallet, and for "
          "a given proposal how they voted (with voting power) and what they posted on its forum thread.",
          {"name": {"type": "string", "description": "Forum username, ENS name or 0x wallet."},
           "proposal_id": _PID_ARG}, ["name"]),
    _tool("search_forum", "Search forum posts and proposal texts by meaning. Use for opinions, arguments, "
          "reasons, concerns and explanations (always for 'why' questions and for who argued what). Each "
          "forum passage comes with its author's wallet and how that wallet voted. Can be limited to one "
          "proposal and/or one author.",
          {"query": {"type": "string", "description": "What to look for, as a full descriptive sentence that "
                     "names the subject, e.g. 'Why did delegates support the DefiLlama grant proposal?'. "
                     "Never single keywords: they match poorly."},
           "proposal_id": _PID_ARG,
           "dao": {"type": "string", "description": "Only passages of this DAO's proposals, e.g. 'arbitrum'. "
                                                    "Use it when the question is about one DAO but no single proposal."},
           "author": {"type": "string", "description": "Only posts by this forum username."},
           "source_type": {"type": "string", "enum": ["proposal_body", "forum_post"],
                           "description": "proposal_body = the proposal's own text (what it asks for); "
                                          "forum_post = only forum discussion. Leave out for both."},
           "n": {"type": "integer", "description": "How many passages (1-8; more is not possible)."}},
          ["query"]),
]


# ── Running a lookup ──────────────────────────────────────────────────────────

def run_tool(conn, name: str, arguments: dict, defaults: dict | None = None):
    """
    Run one lookup and return its raw result. Errors become {"error": ...} so the model
    can read them and try again.

    Parameters (where they come from — features/chat/agent.py gather_evidence):
        conn      - the connection gather_evidence opened.
        name      - the function name the model asked for (tool_call.function.name).
        arguments - the model's arguments, already parsed from JSON. Changed in place:
                    arguments the model left out (or set to null) are filled from `defaults`
                    when the lookup has such a parameter, so what is shown later is what ran.
        defaults  - {"proposal_id": the proposal the user selected, "n": passages requested}.
                    A user who selected a proposal is asking about THAT proposal, however
                    the model phrases its lookup.
    """
    try:
        function = FUNCTIONS[name]
        for key in [k for k, v in arguments.items() if v is None]:
            del arguments[key]
        for key, value in (defaults or {}).items():
            if value is not None and key in inspect.signature(function).parameters:
                arguments.setdefault(key, value)
        return function(conn, **arguments)
    except Exception as e:                       # unknown tool, bad argument, ...
        return {"error": f"{type(e).__name__}: {e}"}


def result_json(result) -> str:
    """A result as JSON text, cut to MAX_RESULT_CHARS."""
    text = json.dumps(result, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + " [...cut]"


def fetcher_view(name: str, result) -> str:
    """
    A result as the AGENT reads it. Passages are shortened to their first VIEW_CHARS
    characters (the agent only needs to see whether they answer the question); the writer
    later gets the full passages from the evidence list.

    Parameters (where they come from): the lookup's name and raw result, from gather_evidence.
    """
    if name == "search_forum" and isinstance(result, dict) and result.get("chunks"):
        result = {"passages": [
            {"source": c["id"], "type": c["metadata"].get("source_type"), "author": c["metadata"].get("author"),
             "proposal": c.get("proposal_title"), "wallet_link": (c.get("sql") or {}).get("link_confidence"),
             "voted": (c.get("sql") or {}).get("voted"), "text": _clip(c["document"], VIEW_CHARS)}
            for c in result["chunks"]]}
    return result_json(result)


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to features/chat/agent.py, which stores the raw result in the evidence
# list and sends fetcher_view() back to the model. The evidence list later reaches
# features/chat/prompt.py (build_prompt), which formats it for the writer.
# If the model names a lookup that does not exist, or a wrong argument: run_tool returns
#   {"error": ...}; the model reads it and can try again within MAX_ROUNDS.
# To add a lookup: write the function here, add it to FUNCTIONS and TOOLS, and add a test
#   in tests/test_tools.py. Its description is what makes the model use it.
