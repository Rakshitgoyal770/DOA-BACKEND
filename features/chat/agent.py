# features/chat/agent.py
"""
features/chat/agent.py — Stage 1: the agent that GATHERS the evidence for a question.

WHAT THIS FILE DOES
    The answer to a governance question needs different data depending on the question:
    "which proposal had the most voters?" needs a ranking over ALL proposals, "what did
    griff say?" needs one person's posts, "why did people support it?" needs forum
    passages. Instead of guessing the data from whatever vector search returned, the LLM
    chooses the lookups (features/chat/tools.py) and we run them:

        1. we send the question + the lookup descriptions            (generate_with_tools)
        2. the model replies "run list_proposals(order_by='voters')"  <- a request, not an answer
        3. WE run it and send the result back                         (tools.run_tool)
        4. repeat until the model has what it needs (it replies with text, or MAX_ROUNDS)

    This agent NEVER writes the answer. It returns the evidence: the list of lookups it
    ran with their raw results. Stage 2 (features/chat/prompt.py build_prompt + llm.py
    generate) writes the single final answer from that evidence, under the strict answer
    rules (citations, [Background] marking, advice mode).

    Why two stages: the answer rules and the data gathering are different jobs. The writer
    sees only the question and the evidence, not the lookup chatter, so its prompt stays
    small, and each stage can be tested on its own.

    SAFETY NET: the model is the only one deciding which lookups to run, so a model that skips
    the forum search leaves the writer without any passage. When the question clearly asks for
    reasons or opinions (wants_passages) and the model ran NO forum search, we run one
    ourselves with the question as written, marked "automatic" in the evidence. A distance or
    reranker score is NOT used to decide this: on our data it let passages through for
    number questions ("which DAO has the most proposals?") and blocked on-topic ones.

WHERE IT SITS
    features/chat/service.py run_chat()
        --> THIS FILE gather_evidence()  --> llm.generate_with_tools (Groq, then Gemini)
                                         --> tools.run_tool  --> SQLite / ChromaDB
        --> prompt.build_prompt(query, evidence) --> llm.generate  (stage 2)

INPUTS
    query       - the user's question.
    proposal_id - optional; the proposal the user selected. Lookups that take a proposal
                  use it whenever the model does not name one.
    n_results   - passages per forum search (ChatRequest.n_results).
"""

import json
import re

from db.schema import get_connection
from features.chat.llm import generate_with_tools
from features.chat.tools import TOOLS, fetcher_view, run_tool

MAX_ROUNDS = 6            # rounds of lookups before we stop and write with what we have
MAX_SEARCHES = 2          # forum searches per question; a third is refused (see gather_evidence)
MAX_LOOKUPS = 6           # lookups of any kind per question; more are refused
SAFETY_NET_PASSAGES = 4   # passages the automatic search asks for (about 770 tokens in the writer's prompt)

# Wording that asks for reasons, opinions or a proposal's content: text, not numbers.
_ARGUING = r"\bwhy\b|\bargu\w*|\bconcern\w*|\breason\w*|\bdiscuss\w*|\b(said|says|say|saying)\b|\bopinion\w*|\bdebat\w*|\bfeel\w*|\bthink\w*"
_TEXT_CUES = re.compile(
    _ARGUING + r"|\bthought\w*|\bcritici[sz]\w*|\bpros\b|\bcons\b|\bin\s+favou?r\b|\bposted\b|\bwrote\b|\bmention\w*"
    r"|\bexplain\b|\bsummari[sz]\w*|\bask(s|ed|ing)?\s+for\b|\bpropos(e|es|ed|ing)\b|\bsupport(ed|s|ers|ing)?\b"
    r"|\boppos(e|ed|es|ing|ition)\b|\bshould\s+(i|we)\b[^?]{0,60}\bvot", re.IGNORECASE)   # not "against": "For / Against" are ballot options
_COUNT_QUESTION = re.compile(r"\bhow\s+(many|much)\b|\bwhat\s+(percentage|share|proportion)\b", re.IGNORECASE)

FETCHER_PROMPT = """You are the research step of a DAO governance assistant. You do NOT answer the user:
a writer will, using only what your lookups return. Your job is to run the lookups that find the
information the question needs, then stop.

How to choose lookups:
- ANY count of people or things ("how many voters", "how many different people discussed / posted",
  turnout, silence ratio) -> proposal_details (voters, forum_posters) or dao_stats. Never count from
  forum passages: a search returns only a few of them, so a count made from them is wrong.
- Ranking, "most", "top", "latest", "closest", "tightest", "most contested", or anything across DAOs ->
  list_proposals (order_by voters / newest / closest) or dao_stats. ONE call answers it. Never go
  through proposals one by one with proposal_details to find the biggest, closest or newest.
- What a proposal asks for / its content / summary -> search_forum with source_type "proposal_body" and
  the proposal_id (the proposal's own text, not forum posts).
- A proposal is named in the question -> find_proposals first (use the proposal whose title matches ALL
  the words you searched for; if two match equally well, look up both), then proposal_details / top_voters.
- A person is named -> person (with the proposal_id when a proposal is known); their words -> search_forum
  with author=.
- Why / what people argued / concerns / support -> search_forum, limited to the proposal when known,
  plus proposal_details for the result.
- "Should I vote ...?" -> proposal_details, and search_forum twice: arguments in favour, arguments against.
- "News", "what's new / happening / going on", "today", "right now", "latest", "open / active votes" ->
  list_proposals with order_by newest: in this assistant, news means the newest proposals and votes.
- General knowledge questions ("what is a DAO?") and greetings ("hi") need no lookup.
- Write each forum search query as a full descriptive sentence that names the subject, for example
  "Why did delegates support the DefiLlama grant proposal?" or "What concerns were raised about the
  Frozen ETH release?". Single keywords ("support", "pros") match poorly and find nothing.
- Run each lookup ONCE. One forum search is enough: do not repeat a search with synonyms or other wording
  when it already returned passages (a "for and against" question may use two searches, one per side).
- If a lookup returns an error or nothing, try different words once; then accept that the data is not there.
When you have what you need, reply with the single word DONE. Do not explain, do not answer."""


def wants_passages(query: str) -> bool:
    """
    True if the question asks for reasons, opinions or what a text says (so forum passages are
    needed). Any count ("how many people discussed it?", "what share had forum discussion?")
    is False: it is answered from the database, and passages next to a count invite the writer
    to count them (it once said 4 where the database said 9).

    Parameter (where it comes from): the user's question, passed on by gather_evidence.
    """
    return bool(_TEXT_CUES.search(query or "")) and not _COUNT_QUESTION.search(query)


def gather_evidence(query: str, proposal_id: str | None = None, n_results: int = 5, on_lookup=None) -> list[dict]:
    """
    Run the model's lookups and return the evidence: [{"tool", "arguments", "result"}, ...]
    in the order they ran. "result" is the RAW lookup result (features/chat/tools.py).
    Empty when the question needs no lookup. A search we ran ourselves because the model
    skipped it (see SAFETY NET above) carries "automatic": True.

    Parameters (where they come from — features/chat/service.py run_chat):
        query       - ChatRequest.query or a golden-dataset question.
        proposal_id - ChatRequest.proposal_id / the golden case's proposal_id.
        n_results   - ChatRequest.n_results (passages per forum search).
        on_lookup   - optional function called with each evidence entry as soon as it ran
                      (the terminal chat uses it to show what is being looked up).
    Raises RuntimeError if every LLM provider fails.
    """
    conn = get_connection()
    try:
        user = query
        if proposal_id:
            title = conn.execute("SELECT title FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
            user = (f"The user selected this proposal and is asking about it: "
                    f"\"{title[0] if title else '?'}\" (proposal_id {proposal_id}).\n\nQuestion: {query}")
        messages = [{"role": "system", "content": FETCHER_PROMPT}, {"role": "user", "content": user}]
        defaults = {"proposal_id": proposal_id, "n": n_results}
        evidence, seen, searches = [], set(), 0

        for _ in range(MAX_ROUNDS):
            reply, _provider = generate_with_tools(messages, TOOLS)
            if not reply.tool_calls:                      # plain text (DONE): nothing more to look up
                break
            messages.append({"role": "assistant", "content": reply.content,
                             "tool_calls": [{"id": tc.id, "type": "function",
                                             "function": {"name": tc.function.name,
                                                          "arguments": tc.function.arguments}}
                                            for tc in reply.tool_calls]})
            for tc in reply.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                if len(evidence) >= MAX_LOOKUPS:
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content":
                                     f"Lookup limit reached ({MAX_LOOKUPS}). Reply DONE; the writer uses what you have."})
                    continue
                result = run_tool(conn, tc.function.name, arguments, defaults)   # fills in defaults
                key = (tc.function.name, json.dumps(arguments, sort_keys=True))
                if key in seen:                           # the same lookup twice adds nothing
                    content = "Already looked up above with these arguments."
                elif tc.function.name == "search_forum" and searches >= MAX_SEARCHES:
                    content = (f"Search limit reached ({MAX_SEARCHES} forum searches). Use the passages you "
                               "already have, or a different lookup, and then reply DONE.")
                else:
                    searches += tc.function.name == "search_forum"
                    seen.add(key)
                    entry = {"tool": tc.function.name, "arguments": arguments, "result": result}
                    evidence.append(entry)
                    content = fetcher_view(tc.function.name, result)
                    if on_lookup:
                        on_lookup(entry)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
        if searches == 0 and wants_passages(query):          # the model skipped the forum search
            arguments = {"query": query, "n": SAFETY_NET_PASSAGES}
            entry = {"tool": "search_forum", "arguments": arguments, "automatic": True,
                     "result": run_tool(conn, "search_forum", arguments, defaults)}   # fills in the proposal
            evidence.append(entry)
            if on_lookup:
                on_lookup(entry)
        return evidence
    finally:
        conn.close()


# ── Where control goes next ───────────────────────────────────────────────────
# Control returns to features/chat/service.py run_chat(), which hands the evidence to
#   features/chat/prompt.py build_prompt() (stage 2) and then to llm.generate().
# If the model keeps asking for lookups: after MAX_ROUNDS we stop and the writer works
#   with what was gathered (it says so when something is missing).
# If every provider fails: generate_with_tools raises RuntimeError -> HTTP 500 / an
#   "error" case in the eval.
# To change WHICH lookups the model picks: edit the descriptions in tools.TOOLS or the
#   guidance in FETCHER_PROMPT, then run the eval (python -m eval.eval_harness).
