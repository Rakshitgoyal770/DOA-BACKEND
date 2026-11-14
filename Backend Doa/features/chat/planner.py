# features/chat/planner.py
"""
features/chat/planner.py — Stage 1, planned version: understand the question once, then run a FIXED set of lookups.

WHAT THIS FILE DOES
    The older stage 1 (features/chat/agent.py) lets the model pick lookups in a loop, so whether
    the forum is searched at all, with what words and scope, depends on the model. Here the
    model does one job, understanding the question, and our code does the rest:

        1. UNDERSTAND   understand()      the kind of question, the DAO, the proposal (title words),
                                          the person, and the question as a search sentence.
                                          Greetings and plain rankings ("most voters", "latest") are
                                          recognised by rules, with no model call; every other
                                          question costs ONE model call that must return a small JSON
                                          object, which is validated (QuestionPlan).
        2. RESOLVE      resolve_proposals the title words become a proposal id (features/chat/tools.py
                                          find_proposals); a proposal the user selected is used as is.
        3. LOOK UP      execute_plan      the lookups for that kind of question, from the table
                                          LOOKUPS below (the same seven lookups the agent had).
        4. SEARCH       execute_plan      passages are retrieved on EVERY question that is about a
                                          proposal's content, arguments or a person; scoped to the proposal
                                          (or DAO, or author) found in step 2 (features/chat/retrieval.py).

    It returns the same evidence list as the agent ([{"tool", "arguments", "result"}]), so the
    writer (features/chat/prompt.py) is unchanged.

    WHICH QUESTIONS GET PASSAGES
    The table below is the decision. Facts-only questions get no passages on purpose: passages
    next to a count invite the writer to count them (it once said 4 where the database said 9).

        kind              lookups                                  passages
        greeting          -                                        -
        general           -                                        -  (the writer uses background)
        ranking           list_proposals                           -
        dao_stats         dao_stats                                -
        proposal_result   proposal_details                         -
        who_voted         proposal_details, top_voters             -  (+ person if one is named)
        person            person                                   their posts (author filter)
        proposal_content  proposal_details                         the proposal's own text
        arguments         proposal_details                         discussion + the proposal's text
        advice            proposal_details                         arguments for, arguments against, the text
        other             -> the agent (agent.py) takes over

    FALLBACK
    If the question cannot be understood (the model's reply is not valid, or the kind is "other"),
    service.py runs the agent instead. If every model provider is down, there is nothing to fall
    back to and the error is raised.

WHERE IT SITS
    features/chat/service.py run_chat() --> THIS FILE --> llm.generate (one call at most),
                                                          tools.py (SQLite lookups, search_forum)
"""

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from db.schema import get_connection
from features.chat.tools import resolve_dao, run_tool

KINDS = ("greeting", "general", "ranking", "dao_stats", "proposal_result", "who_voted", "person",
         "proposal_content", "arguments", "advice", "other")
MAX_PROPOSALS = 2          # proposals looked up when two titles match equally well
BODY_PASSAGES = 2          # passages of the proposal's own text added next to the discussion
MIN_TITLE_MATCH = 0.5      # a proposal is used only if it matches at least this share of the searched words


class PlanError(Exception):
    """The question could not be understood; the caller falls back to the agent."""


class QuestionPlan(BaseModel):
    """What the model (or a rule) understood about a question."""

    model_config = ConfigDict(extra="ignore")          # a model adding a key of its own is not an error

    kind: Literal[KINDS]
    dao: str | None = None                             # a space id after validation (resolve_dao)
    proposal: str | None = None                        # words from the proposal's title
    person: str | None = None                          # forum username, ENS name or wallet
    search: str | None = None                          # the question as a full search sentence
    order_by: Literal["voters", "newest", "closest"] | None = None
    limit: int | None = Field(default=None, ge=1, le=10)
    source: Literal["rules", "model"] = "model"

    @field_validator("dao", mode="before")
    @classmethod
    def _dao_to_space_id(cls, value):
        return resolve_dao(value) if isinstance(value, str) and value.strip() else None

    @field_validator("proposal", "person", "search", mode="before")
    @classmethod
    def _clean(cls, value):
        value = value.strip() if isinstance(value, str) else None
        return value if value and value.lower() not in {"null", "none", "n/a", "unknown"} else None

    @field_validator("order_by", "limit", mode="before")
    @classmethod
    def _blank_is_none(cls, value):
        return None if value in ("", "null", "none") else value


# ── 1. Understand ─────────────────────────────────────────────────────────────

UNDERSTAND_PROMPT = """You read a question about DAO governance (Arbitrum, Aave, Optimism, Uniswap, ENS) and describe it.
You do NOT answer it. Reply with ONE JSON object and nothing else:

{"kind": ..., "dao": ..., "proposal": ..., "person": ..., "search": ..., "order_by": ..., "limit": ...}

kind (choose exactly one):
- "greeting": only a greeting or thanks.
- "general": a general question that needs none of our data ("what is a DAO?").
- "ranking": compares or lists proposals: most voters, newest, latest, closest result, what is new or open now.
- "dao_stats": numbers per DAO: how many proposals, forum coverage, silence ratio, average winning share.
- "proposal_result": the result, winner, turnout or number of voters or forum posters of ONE named proposal.
- "who_voted": which wallets or delegates voted how on ONE proposal, the largest voters.
- "person": about one named person: what they said, how they voted, who they are.
- "proposal_content": what ONE proposal asks for, its text, a summary of it.
- "arguments": why people supported or opposed, what concerns were raised, what was argued, about one proposal or a topic.
- "advice": the user asks how they should vote on it.
- "other": none of these fits, or the question has several unrelated parts.

dao: the DAO the question is about ("arbitrum", "aave", "optimism", "uniswap", "ens"), else null.
proposal: words from the proposal's TITLE as the user wrote them (for example "Frozen ETH" or "DefiLlama grant"), else null.
person: a forum username, ENS name or wallet that the question names, else null.
search: the question rewritten as one full descriptive sentence that names its subject
        (for example "Why did delegates support the DefiLlama grant proposal?"), else null.
order_by: only for "ranking": "voters", "newest" or "closest", else null.
limit: only for "ranking" when the user asks for a number of items (1-10), else null."""

_GREETING = re.compile(r"^\s*(hi|hello|hey|yo|thanks|thank you|thx|good (morning|afternoon|evening))\W*$", re.IGNORECASE)
# A ranking is recognised by rule only when it is plainly one: it names no person and asks no why/who/what-did.
_NOT_A_RANKING = re.compile(r"\b(why|who|whom|whose|how did|what did|argu\w*|said|says|think\w*|"
                            r"concern\w*|reason\w*|should i)\b|[\"“”]", re.IGNORECASE)
_RANK_CLOSEST = re.compile(r"\b(closest|tightest|narrowest|most contested|most controversial)\b", re.IGNORECASE)
_RANK_VOTERS = re.compile(r"\b(most|highest|largest|biggest)\b[^?]{0,40}\b(voters|votes|voted|turnout|participation)\b"
                          r"|\bmost\s+(voted|popular)\b", re.IGNORECASE)
_RANK_NEWEST = re.compile(r"\b(latest|newest|most recent|recent)\b[^?]{0,30}\b(proposals?|votes?)\b"
                          r"|^\s*(what'?s|what is)\s+(new|happening|going on)\b"
                          r"|\b(open|active|ongoing|live)\s+(proposals?|votes?)\b", re.IGNORECASE)


def rule_plan(query: str, proposal_id: str | None = None) -> QuestionPlan | None:
    """
    A plan without asking the model, for the two cases that are plain: a greeting, and a ranking
    of proposals ("which proposal had the most voters?", "what are the latest votes?").
    None for everything else. A question about a proposal the user selected is never a ranking.
    """
    text = query or ""
    if _GREETING.match(text):
        return QuestionPlan(kind="greeting", source="rules")
    if proposal_id or _NOT_A_RANKING.search(text):
        return None
    for pattern, order in ((_RANK_CLOSEST, "closest"), (_RANK_VOTERS, "voters"), (_RANK_NEWEST, "newest")):
        if pattern.search(text):
            number = re.search(r"\b(?:top|latest|last|newest)\s+(\d{1,2})\b", text, re.IGNORECASE)
            return QuestionPlan(kind="ranking", order_by=order, dao=resolve_dao(text),
                                limit=int(number.group(1)) if number and 1 <= int(number.group(1)) <= 10 else None,
                                source="rules")
    return None


def parse_plan(reply: str) -> QuestionPlan:
    """The model's reply as a QuestionPlan. Raises PlanError if it holds no valid JSON object."""
    text = reply or ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise PlanError(f"no JSON object in the reply: {text[:120]!r}")
    try:
        return QuestionPlan(**json.loads(text[start:end + 1]))
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise PlanError(f"the reply is not a valid plan: {str(error).splitlines()[0][:160]}") from error


def understand(query: str, proposal_id: str | None = None, generate=None) -> QuestionPlan:
    """
    The plan for a question: a rule when one applies, else ONE model call.

    Parameters (where they come from — gather_planned):
        query       - the user's question.
        proposal_id - the proposal the user selected, if any (the model is told, so it does not
                      guess a title).
        generate    - llm.generate; tests pass a fake. Raises RuntimeError if every provider fails.
    """
    planned = rule_plan(query, proposal_id)
    if planned:
        return planned
    if generate is None:
        from features.chat.llm import generate
    note = (" The user already selected the proposal this question is about: set proposal to null."
            if proposal_id else "")
    reply, _provider = generate([{"role": "system", "content": UNDERSTAND_PROMPT + note},
                                 {"role": "user", "content": query}])
    return parse_plan(reply)


# ── 2. Resolve ────────────────────────────────────────────────────────────────

def resolve_proposals(found, searched_words: str) -> list[str]:
    """
    The proposal ids a find_proposals result stands for: those that match the most title words,
    at most MAX_PROPOSALS, and only if they match at least MIN_TITLE_MATCH of the searched words
    (a weak match would send the writer the wrong proposal). [] when nothing qualifies.

    Parameters (where they come from — execute_plan): the raw find_proposals result and the words
    searched for.
    """
    if not isinstance(found, list) or not found:
        return []
    words = [w for w in searched_words.lower().replace('"', " ").split() if len(w) > 1]

    def matched(item):
        match = re.match(r"(\d+)", str(item.get("title_words_matched", "")))
        return int(match.group(1)) if match else 0
    best = max(matched(item) for item in found)
    if not words or best / len(words) < MIN_TITLE_MATCH:
        return []
    return [item["proposal_id"] for item in found if matched(item) == best][:MAX_PROPOSALS]


# ── 3 + 4. Look up and search ─────────────────────────────────────────────────

def execute_plan(conn, plan: QuestionPlan, query: str, proposal_id: str | None = None,
                 n_results: int = 5, on_lookup=None) -> list[dict]:
    """
    Run the lookups the table at the top of this file gives for the plan's kind. Returns the evidence:
    [{"tool", "arguments", "result", "planned": True}, ...] in the order they ran.

    Parameters (where they come from — gather_planned):
        conn        - an open SQLite connection.
        plan        - understand()'s result.
        query       - the user's question (the search sentence when the plan has none).
        proposal_id - the proposal the user selected (used instead of the plan's title words).
        n_results   - passages per search.
        on_lookup   - called with each evidence entry as soon as it ran (the terminal chat shows it).
    Raises PlanError for kind "other".
    """
    kind = plan.kind
    if kind == "other":
        raise PlanError("the question does not fit a planned kind")
    evidence: list[dict] = []

    def step(tool, **arguments):
        arguments = {k: v for k, v in arguments.items() if v is not None}
        entry = {"tool": tool, "arguments": arguments, "result": run_tool(conn, tool, arguments), "planned": True}
        evidence.append(entry)
        if on_lookup:
            on_lookup(entry)
        return entry["result"]

    if kind in ("greeting", "general"):
        return evidence
    if kind == "ranking":
        step("list_proposals", order_by=plan.order_by or "voters", dao=plan.dao, limit=plan.limit)
        return evidence
    if kind == "dao_stats":
        step("dao_stats", dao=plan.dao)
        return evidence

    pids = [proposal_id] if proposal_id else []
    if not pids and plan.proposal:
        pids = resolve_proposals(step("find_proposals", words=plan.proposal, dao=plan.dao), plan.proposal)
    sentence = plan.search or query
    # Passages: one proposal when exactly one was found. When two titles matched equally (a temp check
    # and its constitutional vote share their words) the search covers the DAO instead, so the passages
    # of both can come up: each chunk carries its proposal's title in what is embedded.
    scope = {"proposal_id": pids[0]} if len(pids) == 1 else {"dao": plan.dao}

    if kind in ("proposal_result", "who_voted", "proposal_content", "arguments", "advice"):
        for pid in pids:
            step("proposal_details", proposal_id=pid)
    if kind == "who_voted":
        for pid in pids:
            step("top_voters", proposal_id=pid, n=5)
    if kind in ("who_voted", "person") and plan.person:
        step("person", name=plan.person, proposal_id=pids[0] if pids else None)

    if kind == "person" and plan.person:
        step("search_forum", query=sentence, author=plan.person, n=n_results, **scope)
    elif kind == "proposal_content":
        step("search_forum", query=sentence, source_type="proposal_body", n=n_results, **scope)
    elif kind == "arguments":
        step("search_forum", query=sentence, source_type="forum_post", author=plan.person, n=n_results, **scope)
        step("search_forum", query=sentence, source_type="proposal_body", n=BODY_PASSAGES, **scope)
    elif kind == "advice":
        step("search_forum", query=f"Arguments in favour of: {sentence}", source_type="forum_post",
             n=n_results, **scope)
        step("search_forum", query=f"Concerns and arguments against: {sentence}", source_type="forum_post",
             n=n_results, **scope)
        step("search_forum", query=sentence, source_type="proposal_body", n=BODY_PASSAGES, **scope)
    return evidence


def gather_planned(query: str, proposal_id: str | None = None, n_results: int = 5, on_lookup=None,
                   generate=None) -> tuple[list[dict], QuestionPlan]:
    """
    Stage 1, planned version: (evidence, plan). Raises PlanError when the question cannot be planned
    (the caller falls back to the agent) and RuntimeError when every model provider failed.

    Parameters (where they come from — features/chat/service.py run_chat): query, the selected
    proposal_id, n_results and on_lookup as in agent.gather_evidence; generate is for tests.
    """
    plan = understand(query, proposal_id, generate)
    conn = get_connection()
    try:
        return execute_plan(conn, plan, query, proposal_id, n_results, on_lookup), plan
    finally:
        conn.close()


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to features/chat/service.py, which hands the evidence to
#   features/chat/prompt.py build_prompt() (stage 2), then checks the answer's citations
#   (features/chat/citations.py).
# To change which lookups a kind gets: the table above and execute_plan.
# To add a kind: KINDS, UNDERSTAND_PROMPT, execute_plan, and a case in tests/test_planner.py.
# If a question is misunderstood: the plan is returned by run_chat()["plan"] (and POST /chat "plan").
