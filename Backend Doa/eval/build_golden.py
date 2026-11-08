# eval/build_golden.py
"""
eval/build_golden.py — Builds the generated part of the golden dataset from the real database.

WHAT THIS FILE DOES
    Writes eval/golden_generated.json: test questions of every type, from broad
    (all DAOs) to narrow (one delegate's vote), each with the exact answer we
    expect. Nothing is typed by hand: every expected number, name and source id
    is read from SQLite here.

    The expected numbers are computed with RAW SQL written in this file, NOT
    with features/metrics.py. If the app's formulas had a bug, an expected value
    built with them would contain the same bug and the test would still pass.
    tests/test_golden.py checks that both independent calculations agree.

    Only proposals that can no longer change are used for exact numbers:
    closed, scores "final", and every vote stored. Cases that depend on time
    ("most recent", averages over all proposals) are marked "volatile": true
    and must be regenerated after a sync.

QUESTION TYPES (level / intent)
    dashboard  compare, record, overview         questions across all DAOs
    dao        coverage, recent, closest         questions about one DAO
    proposal   result, turnout, concentration,   questions about one proposal
               posters, explain (+ an unscoped variant)
    detail     who_said, author_vote, ranked_vote   one person's post or vote
    behaviour  advice, background, mixed, unanswerable, out_of_scope,
               ambiguous, nonexistent           how the assistant must behave

RUN
    python -m eval.build_golden          (reads db/ and chroma_data/, no network)

WHERE IT SITS
    SQLite + ChromaDB --> THIS FILE --> eval/golden_generated.json
        --> eval/golden_dataset.py (adds the hand-written cases) --> eval/eval_harness.py
"""

import datetime
import json
from pathlib import Path

from db.schema import get_connection

OUT_PATH = Path(__file__).with_name("golden_generated.json")

# Proposals whose numbers can never change again.
STABLE_SQL = """
    p.state = 'closed' AND p.scores_state = 'final'
    AND (SELECT COUNT(*) FROM votes v WHERE v.proposal_id = p.id) >= p.votes_count
    AND p.votes_count > 0
"""


# ── Independent calculations (raw SQL, deliberately NOT features/metrics.py) ──

def raw_result(conn, pid: str) -> dict:
    """Winning choice name and its share (%), straight from proposals.scores_json."""
    p = conn.execute("SELECT choices_json, scores_json, scores_total FROM proposals WHERE id = ?", (pid,)).fetchone()
    choices, scores = json.loads(p["choices_json"]), json.loads(p["scores_json"])
    best = max(range(len(scores)), key=lambda i: scores[i])
    return {"winner": choices[best], "winner_pct": round(100 * scores[best] / p["scores_total"], 1)}


def raw_top4_pct(conn, pid: str) -> float:
    """Top-4 wallets' share of all stored voting power, by SQL alone."""
    top, total = conn.execute(
        """SELECT (SELECT SUM(vp) FROM (SELECT vp FROM votes WHERE proposal_id = ? ORDER BY vp DESC LIMIT 4)),
                  (SELECT SUM(vp) FROM votes WHERE proposal_id = ?)""", (pid, pid)).fetchone()
    return round(100 * top / total, 1)


def raw_posters(conn, pid: str) -> int:
    return conn.execute("SELECT COUNT(DISTINCT lower(username)) FROM forum_posts WHERE proposal_id = ?",
                        (pid,)).fetchone()[0]


def raw_dao_silence(conn) -> dict[str, float]:
    """Average over a DAO's proposals of posters / voters (%), like GET /daos reports it."""
    rows = conn.execute("""
        SELECT p.space_id, p.votes_count,
               (SELECT COUNT(DISTINCT lower(username)) FROM forum_posts f WHERE f.proposal_id = p.id) AS posters
        FROM proposals p WHERE p.votes_count > 0""").fetchall()
    per_dao: dict[str, list[float]] = {}
    for r in rows:
        per_dao.setdefault(r["space_id"], []).append(100 * r["posters"] / r["votes_count"])
    return {dao: round(sum(v) / len(v), 3) for dao, v in per_dao.items()}


# ── Picking the proposals and people the questions are about ─────────────────

def dao_names(conn) -> dict[str, str]:
    return {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM spaces")}


def featured_proposals(conn) -> dict[str, dict]:
    """Per DAO: its most-voted stable proposal that has forum discussion."""
    out = {}
    for (space,) in conn.execute("SELECT id FROM spaces ORDER BY id"):
        row = conn.execute(f"""
            SELECT p.id, p.title, p.votes_count FROM proposals p
            WHERE p.space_id = ? AND {STABLE_SQL}
              AND EXISTS (SELECT 1 FROM forum_posts f WHERE f.proposal_id = p.id)
            ORDER BY p.votes_count DESC LIMIT 1""", (space,)).fetchone()
        if row:
            out[space] = dict(row)
    return out


def contested_proposal(conn, space: str) -> dict:
    """
    The DAO's stable proposal with the smallest winning share (the closest vote).
    Only proposals with two or three options count: in an election with nine
    candidates a winner on 18.5% is normal, not a close vote.
    """
    best = None
    for p in conn.execute(f"SELECT p.id, p.title, p.choices_json FROM proposals p "
                          f"WHERE p.space_id = ? AND {STABLE_SQL}", (space,)):
        if len(json.loads(p["choices_json"])) > 3:
            continue
        share = raw_result(conn, p["id"])["winner_pct"]
        if best is None or share < best["winner_pct"]:
            best = {"id": p["id"], "title": p["title"], "winner_pct": share}
    return best


def linked_voters(conn, n: int) -> list[dict]:
    """(author, proposal) pairs: a high/certain-confidence linked forum author who
    posted on a stable proposal AND voted on it, biggest voting power first,
    one pair per author."""
    rows = conn.execute(f"""
        SELECT lower(f.username) AS author, f.proposal_id, p.title, p.choices_json,
               v.vp, v.choice_json, MIN(f.id) AS first_post
        FROM forum_posts f
        JOIN resolved_identities r ON r.forum_username = lower(f.username)
        JOIN proposals p ON p.id = f.proposal_id
        JOIN votes v ON v.proposal_id = f.proposal_id AND lower(v.voter) = lower(r.wallet_address)
        WHERE r.confidence_level IN ('high', 'certain') AND length(f.content) > 200 AND {STABLE_SQL}
        GROUP BY lower(f.username), f.proposal_id
        ORDER BY v.vp DESC""").fetchall()
    picked, seen = [], set()
    for r in rows:
        if r["author"] not in seen:
            seen.add(r["author"])
            picked.append(dict(r))
        if len(picked) == n:
            break
    return picked


def raw_choice_names(choice_json: str, choices: list[str]):
    """Choice numbers -> names, written independently of metrics.decode_choice."""
    raw = json.loads(choice_json)
    if isinstance(raw, int):
        return [choices[raw - 1]]
    if isinstance(raw, list):
        return [choices[i - 1] for i in raw]
    return [choices[int(k) - 1] for k in raw]


def post_ids(conn, pid: str, author: str) -> list[str]:
    """
    Post-level ids of an author's posts on a proposal: forum_post_<proposal>_<post>.
    A long post is stored as several chunks (..._c0, ..._c1); eval/checks.py treats every
    chunk as its post, so the post-level id is what the dataset needs.
    """
    return [f"forum_post_{pid}_{r[0]}" for r in conn.execute(
        "SELECT id FROM forum_posts WHERE proposal_id = ? AND lower(username) = ? AND content != ''",
        (pid, author))]


def body_chunk_ids(pid: str, conn) -> list[str]:
    """Index ids of a proposal body's chunks, chunked exactly as vector/embedding.py does it."""
    from vector.chunking import PROPOSAL_MAX_CHARS, chunk_text
    from vector.embedding import get_model, token_counter
    body = conn.execute("SELECT body FROM proposals WHERE id = ?", (pid,)).fetchone()[0]
    chunks = chunk_text(body, PROPOSAL_MAX_CHARS, token_counter(get_model()))
    return [f"proposal_{pid}_{i}" for i in range(len(chunks))]


# ── Case builder ──────────────────────────────────────────────────────────────

def case(cid, level, intent, question, scope=None, numbers=None, mentions=None, sources=None,
         behavior="answer", volatile=False, needs=None, note=None) -> dict:
    """
    One golden case.
        numbers  - [{"label", "value", "kind"}]: kind "pct" (±0.2), "count" (exact), "vp" (±1%)
        mentions - strings the answer must contain ("title:" prefix = most words of a title)
        sources  - index ids; at least one must be retrieved
        behavior - answer | no_recommendation | say_insufficient | ask_clarify | background_tagged
        needs    - the feature the case depends on, if the system lacks it today
    """
    return {"id": cid, "level": level, "intent": intent, "question": question,
            "scope": scope or {}, "expected": {"numbers": numbers or [], "mentions": mentions or [],
                                               "sources": sources or [], "behavior": behavior},
            "volatile": volatile, "needs": needs, "note": note}


def build(conn) -> list[dict]:
    names = dao_names(conn)
    feat = featured_proposals(conn)
    spaces = sorted(feat)
    cases = []

    # ── dashboard: across all DAOs ────────────────────────────────────────────
    silence = raw_dao_silence(conn)
    top_dao = max(silence, key=silence.get)
    cases.append(case("dash_compare_silence", "dashboard", "compare",
                      "Across the DAOs you track, which one has the highest average silence ratio "
                      "(forum posters as a share of voters)?",
                      mentions=[names[top_dao]], numbers=[{"label": "silence %", "value": silence[top_dao], "kind": "pct"}],
                      volatile=True, needs="cross-DAO SQL facts (compare_daos)"))
    rec = conn.execute(f"SELECT p.id, p.title, p.votes_count FROM proposals p WHERE {STABLE_SQL} "
                       "ORDER BY p.votes_count DESC LIMIT 1").fetchone()
    cases.append(case("dash_record_turnout", "dashboard", "record",
                      "Which proposal across all the DAOs had the most voters, and how many voted?",
                      mentions=[f"title:{rec['title']}"], numbers=[{"label": "voters", "value": rec["votes_count"], "kind": "count"}],
                      needs="cross-DAO SQL facts"))
    recent = [r["title"] for r in conn.execute("SELECT title FROM proposals ORDER BY created_ts DESC LIMIT 3")]
    cases.append(case("dash_overview_recent", "dashboard", "overview",
                      "What are the most recent proposals across the DAOs you track?",
                      mentions=[f"title:{t}" for t in recent], volatile=True, needs="recent_proposals SQL facts"))

    # ── dao: one DAO (ENS and Arbitrum) ───────────────────────────────────────
    for space in ("ens.eth", "arbitrumfoundation.eth"):
        short = space.split(".")[0]
        total, with_forum = conn.execute("""
            SELECT COUNT(*), SUM(EXISTS (SELECT 1 FROM forum_posts f WHERE f.proposal_id = p.id))
            FROM proposals p WHERE p.space_id = ?""", (space,)).fetchone()
        cases.append(case(f"dao_{short}_coverage", "dao", "coverage",
                          f"What share of {names[space]} proposals had forum discussion?",
                          scope={"dao_id": space},
                          numbers=[{"label": "forum coverage %", "value": round(100 * with_forum / total, 1), "kind": "pct"}],
                          volatile=True, needs="DAO scope + DAO SQL facts"))
        last = conn.execute(f"SELECT p.title FROM proposals p WHERE p.space_id = ? AND {STABLE_SQL} "
                            "ORDER BY p.end_ts DESC LIMIT 1", (space,)).fetchone()
        cases.append(case(f"dao_{short}_recent", "dao", "recent",
                          f"What was the most recent {names[space]} proposal to finish voting?",
                          scope={"dao_id": space}, mentions=[f"title:{last['title']}"],
                          volatile=True, needs="DAO scope + recent_proposals"))
        close = contested_proposal(conn, space)
        cases.append(case(f"dao_{short}_closest", "dao", "closest",
                          f"Among {names[space]} proposals with two or three options (such as For / Against), "
                          "which had the closest vote, and what share did the winner get?",
                          scope={"dao_id": space}, mentions=[f"title:{close['title']}"],
                          numbers=[{"label": "winner %", "value": close["winner_pct"], "kind": "pct"}],
                          volatile=True, needs="DAO scope + DAO SQL facts"))

    # ── proposal: one proposal, spread over the five DAOs ─────────────────────
    templates = [
        ("result", "What was the result of the proposal \"{t}\"?",
         lambda pid: ([{"label": "winner %", "value": raw_result(conn, pid)["winner_pct"], "kind": "pct"}],
                      [raw_result(conn, pid)["winner"]])),
        ("turnout", "How many wallets voted on \"{t}\"?",
         lambda pid: ([{"label": "voters", "value": conn.execute("SELECT votes_count FROM proposals WHERE id = ?", (pid,)).fetchone()[0], "kind": "count"}], [])),
        ("concentration", "What share of the voting power did the top 4 voters hold on \"{t}\"?",
         lambda pid: ([{"label": "top-4 %", "value": raw_top4_pct(conn, pid), "kind": "pct"}], [])),
        ("posters", "How many different people discussed \"{t}\" on the forum?",
         lambda pid: ([{"label": "forum posters", "value": raw_posters(conn, pid), "kind": "count"}], [])),
    ]
    for i, (intent, q, expect) in enumerate(templates):
        for space in (spaces[i % len(spaces)], spaces[(i + 2) % len(spaces)]):
            p = feat[space]
            nums, ments = expect(p["id"])
            cases.append(case(f"prop_{intent}_{space.split('.')[0]}", "proposal", intent, q.format(t=p["title"]),
                              scope={"proposal_id": p["id"]}, numbers=nums, mentions=ments))
    for space in (spaces[0], spaces[3]):
        p = feat[space]
        cases.append(case(f"prop_explain_{space.split('.')[0]}", "proposal", "explain",
                          f"What does the proposal \"{p['title']}\" ask for?",
                          scope={"proposal_id": p["id"]}, sources=body_chunk_ids(p["id"], conn)))
    p = feat[spaces[1]]
    nums, ments = templates[0][2](p["id"])
    cases.append(case("prop_result_unscoped", "proposal", "result_unscoped",
                      f"What was the result of the proposal \"{p['title']}\"?", numbers=nums, mentions=ments,
                      note="no proposal_id: the system must find the proposal from its title"))

    # ── detail: one person ────────────────────────────────────────────────────
    for k, v in enumerate(linked_voters(conn, 2)):
        choices = json.loads(v["choices_json"])
        cases.append(case(f"detail_who_said_{k + 1}", "detail", "who_said",
                          f"What did {v['author']} say on the forum about \"{v['title']}\"?",
                          scope={"proposal_id": v["proposal_id"]}, mentions=[v["author"]],
                          sources=post_ids(conn, v["proposal_id"], v["author"])))
        cases.append(case(f"detail_author_vote_{k + 1}", "detail", "author_vote",
                          f"How did {v['author']} vote on \"{v['title']}\", and with how much voting power?",
                          scope={"proposal_id": v["proposal_id"]},
                          mentions=raw_choice_names(v["choice_json"], choices)[:1],
                          numbers=[{"label": "voting power", "value": round(v["vp"], 2), "kind": "vp"}]))
    ranked = conn.execute(f"""
        SELECT p.id, p.title, p.choices_json, v.choice_json, v.vp FROM proposals p JOIN votes v ON v.proposal_id = p.id
        WHERE {STABLE_SQL} AND (v.choice_json LIKE '[%,%' OR v.choice_json LIKE '{{%')
        ORDER BY v.vp DESC LIMIT 1""").fetchone()
    cases.append(case("detail_ranked_vote", "detail", "ranked_vote",
                      f"How did the largest voter on \"{ranked['title']}\" fill in their ballot?",
                      scope={"proposal_id": ranked["id"]},
                      mentions=raw_choice_names(ranked["choice_json"], json.loads(ranked["choices_json"]))[:1],
                      numbers=[{"label": "voting power", "value": round(ranked["vp"], 2), "kind": "vp"}],
                      needs="largest-voter facts (top voters with choices) in the prompt"))

    # ── behaviour: how the assistant must act ─────────────────────────────────
    a, b = feat[spaces[2]], feat[spaces[4]]
    for p in (a, b):
        nums, _ = templates[0][2](p["id"])
        cases.append(case(f"beh_advice_{p['id'][:8]}", "behaviour", "advice",
                          f"Should I vote for \"{p['title']}\"?", scope={"proposal_id": p["id"]},
                          numbers=nums, behavior="no_recommendation", needs="advice mode"))
    cases.append(case("beh_background", "behaviour", "background",
                      "What is a delegate in DAO governance?", behavior="background_tagged",
                      note="general knowledge is allowed but every such sentence must be marked [Background]"))
    turnout = conn.execute("SELECT votes_count FROM proposals WHERE id = ?", (a["id"],)).fetchone()[0]
    cases.append(case("beh_mixed", "behaviour", "mixed",
                      f"What is Snapshot, and how many voters did \"{a['title']}\" have?",
                      scope={"proposal_id": a["id"]}, behavior="background_tagged",
                      numbers=[{"label": "voters", "value": turnout, "kind": "count"}]))
    cases.append(case("beh_unanswerable", "behaviour", "unanswerable",
                      f"What was the token price on the day \"{a['title']}\" closed?",
                      scope={"proposal_id": a["id"]}, behavior="say_insufficient",
                      note="we hold no price data"))
    cases.append(case("beh_out_of_scope", "behaviour", "out_of_scope",
                      "What did Compound governance vote on last month?", behavior="say_insufficient",
                      note="Compound is not one of the DAOs we track"))
    cases.append(case("beh_ambiguous", "behaviour", "ambiguous",
                      "How should I vote on this proposal?", behavior="ask_clarify",
                      needs="question understanding (ask which proposal)",
                      note="no proposal_id and no title: the assistant cannot know which one"))
    cases.append(case("beh_nonexistent", "behaviour", "nonexistent",
                      "What was the result of the proposal \"Fund a permanent lunar research base\"?",
                      behavior="say_insufficient", note="no such proposal exists"))
    return cases


def main():
    conn = get_connection()
    try:
        cases = build(conn)
    finally:
        conn.close()
    OUT_PATH.write_text(json.dumps({
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "note": "Generated by eval/build_golden.py from the real database. Do not edit by hand; re-run instead.",
        "cases": cases,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(cases)} cases to {OUT_PATH}")


if __name__ == "__main__":
    main()


# ── Where control goes next ───────────────────────────────────────────────────
# eval/golden_dataset.py loads the file written here and adds the hand-written
# cases; eval/eval_harness.py runs them. Re-run this after a data sync so the
# "volatile" cases match the new data (tests/test_golden.py flags drift).
