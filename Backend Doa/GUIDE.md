# Project Guide — understand the code in one read

A quick reference for this repository. Read **section 1** for the big picture,
**section 2** to follow one question through the code, **section 3** to see how
data gets in, and use **sections 4–7** to look things up.

Every Python file also explains itself: a header at the top (what it does,
where it sits, its inputs), a note on every function saying *where each
parameter comes from*, and a **"Where control goes next"** section at the bottom.
This guide is the map; the files are the detail.

---

## 1. The big picture (60 seconds)

The project answers questions about how DAOs govern, by joining two kinds of data:

| Data | Comes from | Tells us |
|:---|:---|:---|
| **Proposals and votes** | Snapshot (on-chain voting) | who voted, how, with how much voting power |
| **Forum posts** | Discourse forums | what people argued and why |
| **Wallet ↔ username links** | our identity-linking strategies | which forum author is which voting wallet |

```
            OUTSIDE                      OUR STORAGE                     WHAT USERS GET
  Snapshot ─┐                       ┌─ SQLite (facts, exact) ───────┐
            ├─ sync (features/…/fetch.py) ┤                            ├─ API: /daos /proposals /identities
  Discourse ┘                       └─ ChromaDB (text, by meaning) ─┤
                                                                     └─ /chat: RAG answer with citations
```

- **SQLite** holds the facts: every proposal, vote, forum post and link. Found by id.
- **ChromaDB** holds the *text* (proposal paragraphs, forum posts) as vectors, so the chat
  can find passages by meaning. It is rebuilt from SQLite, never the other way round.
- **The LLM never touches the database.** It can only *ask* for lookups by name
  (`list_proposals`, `person`, `search_forum` …). Our code runs them on SQLite / ChromaDB and
  sends the results back as text. It never writes SQL and never computes a number.

---

## 2. Follow one chat question, file by file

Example: `POST /chat {"query": "Why did people support it?", "proposal_id": "0xe97a…" }` (DefiLlama).

| # | File | Function | What happens | Output |
|:-:|:---|:---|:---|:---|
| 1 | [main.py](main.py) | — | The request matches the `/chat` router | → routes |
| 2 | [features/chat/routes.py](features/chat/routes.py) | `chat` | Validates the body (`query` 3–2000 chars, `n_results` 1–20) | → `run_chat` |
| 3 | [features/chat/service.py](features/chat/service.py) | `run_chat` | Two stages: gather the evidence, then write the answer. **Same function the terminal chat and the evaluation use.** | one answer + sources + lookups |
| 3b | [features/chat/planner.py](features/chat/planner.py) | `gather_planned` | **Stage 1, the default.** The question is understood once (rules for greetings and plain rankings, otherwise ONE model call that returns a validated JSON plan: kind, DAO, proposal, person, search sentence). Our code then runs a FIXED set of lookups for that kind, and searches passages on every question about content, arguments or a person, scoped to what was found. Falls back to step 4 if the question cannot be understood. `CHAT_PIPELINE=agent` skips it | evidence |
| 4 | [features/chat/agent.py](features/chat/agent.py) | `gather_evidence` | **Stage 1, the fallback (and `CHAT_PIPELINE=agent`).** Sends the question and the lookup descriptions to the LLM. The LLM replies "run `search_forum(...)`" (a request, not an answer); we run it and send the result back; repeat until it says `DONE` (max 6 rounds, max 2 forum searches). It never writes the answer. If the question asks for reasons or opinions and the model skipped the forum search, we run it ourselves (`automatic`). | evidence list |
| 5 | [features/chat/llm.py](features/chat/llm.py) | `generate_with_tools` | One round of step 4: Groq, then Gemini, then Groq's small model (a separate daily quota) if one fails (waits ≤15 s for a rate limit; 45 s timeout) | the model's reply |
| 6 | [features/chat/tools.py](features/chat/tools.py) | `run_tool` + 7 lookups | The lookups the LLM may request: `find_proposals`, `list_proposals`, `dao_stats`, `proposal_details`, `top_voters`, `person`, `search_forum`. Each reads SQLite / ChromaDB. A proposal the user selected is filled in when the model leaves it out. | raw results |
| 7 | [features/chat/retrieval.py](features/chat/retrieval.py) | `retrieve` | Used by `search_forum`: runs a vector search (meaning) and a BM25 keyword search ([vector/keyword_index.py](vector/keyword_index.py)) over the same chunks, merges the two rankings, drops chunks too far from the question (0.9 anywhere, 0.95 inside one proposal, 1.0 for one author) and lets a reranker ([vector/reranker.py](vector/reranker.py)) put the best first. Measure it with `python -m eval.retrieval_eval` (no LLM calls) | chunks |
| 8 | [features/chat/context.py](features/chat/context.py) | `proposal_facts`, `author_context` | One proposal's numbers; a forum author's wallet and **how that wallet voted** (attached to every forum passage) | numbers, `chunk["sql"]` |
| 9 | [features/metrics.py](features/metrics.py) | `top_voter_share`, `silence_ratio_pct`, … | The formulas behind the numbers (the **same** ones the endpoints use) | numbers |
| 10 | [features/chat/prompt.py](features/chat/prompt.py) | `build_prompt` | **Stage 2.** Turns the evidence into the writer's prompt: system rules + `DATABASE FACTS` (one entry per lookup) + numbered sources + question | 2 messages |
| 11 | [features/chat/llm.py](features/chat/llm.py) | `generate` | Tries Groq → Gemini → OpenRouter until one answers | the single final answer |

**The two stages in one picture:**
```
STAGE 1  agent (gathers)                                    STAGE 2  writer (answers)
question ──> LLM: "run list_proposals(...)"                 question + evidence
             we run it on SQLite, send the result back  ──>  system rules (cite, [Background], advice)
             LLM: "run search_forum(...)" ... "DONE"         one LLM call -> ONE answer
```

**Why not just search?** Vector search finds *similar text*; it cannot rank ("most voters"), count, or
find "what griff voted". Those need SQL, so the LLM picks the lookup and our code computes the number.

**What the writer actually receives (step 10):**
```
DATABASE FACTS (lookups run in the database for this question):
- proposal_details(proposal_id=0xe97a...):
  {"dao": "Optimism Collective", "title": "Season 2: Cycle 8: DefiLlama", "winning_choice": "For",
   "total_voters": 14194, "forum_posters": 12, "silence_ratio_pct": 0.085, ...}

Sources:
[Source 1 - forum_post by OPUser (voting power 9.0K, voted For, wallet link: high)] Glad to see you here...
[Source 2 - proposal_body] This Governance Fund Phase 1 proposal is eligible...

Question: Why did people support it?
```

**If something goes wrong:** the question matches nothing or needs no lookup → still HTTP 200, the writer
says it has no data (or gives `[Background]` knowledge) · invalid body → 422 · every LLM provider fails → 500 ·
the LLM asks for a lookup that does not exist → it gets an error message and can retry.

---

## 3. How data gets in (the sync)

Run order matters, because each step needs the previous one:

| # | File | Function | What it does | Needs |
|:-:|:---|:---|:---|:---|
| 1 | [features/sync/runner.py](features/sync/runner.py) | `sync_all` | Runs 2 → 3 → 4 → 5 | — |
| 2 | [features/proposals/fetch.py](features/proposals/fetch.py) | `sync_proposals` | DAO rows; every **unfinished** proposal re-read **by id**; every proposal published since our newest | — |
| 3 | [features/forum/fetch.py](features/forum/fetch.py) | `fetch_forum_threads` | **Every** post of each linked thread (Discourse gives 20 per page; the rest are fetched by id) | discussion links from 2 |
| 4 | [features/votes/fetch.py](features/votes/fetch.py) | `fetch_all_votes` | **Every** vote of proposals whose votes are missing/partial, resuming from the newest stored vote | vote counts from 2 |
| 5 | [features/sync/audit.py](features/sync/audit.py) | `audit_collection_status` | Reports what is complete (`/sync/status`, `--check`) | — |

Then, outside `sync_all`:

| Step | Command | Why |
|:---|:---|:---|
| Re-check wallet links | `python -m features.identity.runner --upgrade` | new votes/posts can confirm or create links (offline, seconds) |
| Update the search index | `python -m vector.embedding` | new posts become searchable; only new/changed text is embedded |

**All of it as one unattended job:** [features/sync/refresh.py](features/sync/refresh.py) (`python -m features.sync.refresh`)
takes a verified database backup (`backups/`, newest 5 kept), repeats `sync_all` until nothing is left to fetch,
re-checks the wallet links, syncs the index and validates it. It writes `logs/last_refresh.json` (`ok`, `problems`,
`warnings`, row counts before and after) and exits 1 when there are problems. Only one refresh runs at a time.
[scripts/register_refresh_task.ps1](scripts/register_refresh_task.ps1) registers it as a daily Windows scheduled task.

**The pattern every fetcher follows** (learn it once):
```
1. Ask the source what EXISTS        (votes_count / thread post ids / proposal ids)
2. Compare with what we STORED       (one completeness rule, shared by fetcher + audit)
3. Fetch only the DIFFERENCE         (time-cursor paging or batches; resume where we stopped)
4. Write idempotently                (upsert on the right key: re-running never duplicates)
5. Record failures                   (the audit shows them; the next run retries)
```

**Time-cursor paging** ([clients/snapshot.py](clients/snapshot.py) `_iter_by_created`): Snapshot gives
max 1,000 items per request and refuses `skip` > 5,000, so we ask "created ≥ the last time I saw",
page after page. No limit, and items sharing a second are not lost.

---

## 4. Where every rule lives (one home each)

| Rule | File | Used by |
|:---|:---|:---|
| Forum posters, silence ratio, winning share, top-voter share, choice names | [features/metrics.py](features/metrics.py) | DAO + proposal endpoints, chat |
| Is a proposal's vote data complete? | [features/votes/completeness.py](features/votes/completeness.py) | vote fetcher, audit, metrics |
| Is a forum thread complete? | [features/forum/completeness.py](features/forum/completeness.py) | forum fetcher, audit |
| The chat pipeline | [features/chat/service.py](features/chat/service.py) `run_chat` | `POST /chat`, evaluation |
| What the LLM is told | [features/chat/prompt.py](features/chat/prompt.py) `SYSTEM_PROMPT` | every answer |
| Writing a wallet link (never weakens a stronger one) | [features/identity/common.py](features/identity/common.py) `upsert_identity` | every identity strategy |
| What the search index should contain | [vector/embedding.py](vector/embedding.py) `sync_index` | index sync |
| What metadata every chunk carries (the schema) | [vector/chunk_metadata.py](vector/chunk_metadata.py) `ChunkMetadata` | index sync, search filters |
| How text is split into chunks (sizes, why, where) | [vector/chunking.py](vector/chunking.py) | index sync, prompt |
| Opening the database (and upgrading its schema) | [db/schema.py](db/schema.py) `get_connection` | everything |
| Which DAOs we follow | [config/curated_daos.py](config/curated_daos.py) | proposal sync, `/daos` |

Change a rule in its home and every user of it changes together.

---

### Chunking: every strategy in use, why, and where

The embedding model reads at most **512 tokens** per text and silently ignores the rest, so a long
text must be cut into chunks or most of it can never be found. The full explanation is in the
header of [vector/chunking.py](vector/chunking.py).

| What | Strategy | Limit | Where |
|:---|:---|:---|:---|
| **Proposal body** | Pack whole paragraphs together; split a too-long paragraph by sentence | 1,500 characters | `vector/embedding.py` `proposal_documents` |
| **Forum post** | A post that fits stays ONE chunk (id unchanged); a longer one is split by sentence | 1,200 characters | `vector/embedding.py` `forum_documents` |
| **Both of the above** | A second limit counted in the model's own tokens, because URLs, tables and hashes use many tokens per character | 500 tokens | `vector/chunking.py` `chunk_text` |
| **Prompt, per source** | Not chunking: a safety cut so one oversized source cannot push a request over the free LLM limit | 2,000 characters | `features/chat/prompt.py` `clip_source` |

How a text is cut: paragraphs first, then sentences, then words (only for text with no sentence
breaks, like a pasted table). Forum posts need the sentence level because our HTML cleaner removes all
line breaks. There is **no overlap** between chunks (splits land on sentence ends). Every chunk of a post
keeps the post's author and wallet. Ids: a post in one chunk keeps `forum_post_<proposal>_<post>`; a split
post becomes `..._c0`, `..._c1`, … (the evaluation counts any chunk as its post).

Before this was added, 17% of forum posts were longer than the limit and **46.8% of all forum text was
invisible to search**.

## 5. The database at a glance

| Table | One row per | Written by | Key facts |
|:---|:---|:---|:---|
| `spaces` | DAO | proposals sync | name, network, Snapshot's totals |
| `proposals` | proposal | proposals sync | title, body, choices, scores, `votes_count`, `scores_state`, `discussion_url` |
| `votes` | (proposal, voter) | votes sync | voter wallet, choice, voting power `vp` |
| `forum_posts` | (proposal, post) | forum sync | username, content. Key is **(proposal_id, id)**: post ids repeat across forums |
| `forum_threads` | thread | forum sync | posts Discourse listed, unavailable, last error |
| `resolved_identities` | forum user | identity strategies | wallet, confidence (low/medium/high/certain), method |
| `wallet_ens` | wallet | voter ENS strategy | verified ENS name cache |

How they connect:
```
spaces ─< proposals ─< votes (voter wallet)
                  └─< forum_posts (username) ── resolved_identities ── wallet = votes.voter
```

---

## 6. Commands cheat sheet

| I want to… | Run |
|:---|:---|
| Start the API (docs at `/docs`) | `uvicorn main:app --reload --port 8000` |
| **Chat with the project in the terminal** | `python -m features.chat.cli` (then `/find`, `/use`, `/lookups`, `/sources`, `/help`; it prints each lookup as the agent runs it) |
| See what data we have / what's missing | `python -m features.sync.runner --check` |
| **Bring everything up to date in one go** (backup, data, wallet links, index, check) | `python -m features.sync.refresh` (then read `logs/last_refresh.json`) |
| Schedule that to run every day (Windows) | `powershell -ExecutionPolicy Bypass -File scripts\register_refresh_task.ps1` |
| Bring only the data up to date | `python -m features.sync.runner --sync-all` |
| Backfill many votes or threads | `--fetch-votes --limit 200` · `--fetch-forum --limit 200` |
| Re-check wallet links (fast, offline) | `python -m features.identity.runner --upgrade` |
| Run every linking strategy (network, minutes) | `python -m features.identity.runner --all` |
| Update the search index | `python -m vector.embedding` (add `--dry-run` to preview) |
| Check my LLM keys work | `python -m features.chat.llm` |
| Run the tests | `python -m pytest` |
| Refresh the generated golden questions (after a sync) | `python -m eval.build_golden` |
| Run the golden dataset: pass/fail per question type (LLM calls) | `python -m eval.eval_harness` (planned pipeline, the default) |
| …the same dataset on the older agent, to compare | `$env:CHAT_PIPELINE="agent"; python -m eval.eval_harness` (PowerShell) |
| …only some cases | `python -m eval.eval_harness --only proposal` (a level, type, or case id) |
| …plus faithfulness / relevancy scores (3x more LLM calls) | `python -m eval.eval_harness --judge` |
| Re-score a saved run with updated checks (no LLM calls) | `python -m eval.eval_harness --regrade eval/results/run_<date>.json` |

**Which Python?** The project has its own `.venv`, which has `groq` and `mistralai`; the global Python
does not, so every LLM call falls through to the slow free OpenRouter models (and a missing provider
can end a run with "All providers failed"). Run the evaluation and the API with the `.venv` interpreter
(`.venv\Scripts\python -m eval.eval_harness`, or activate it first). A case that ends in an **ERROR** is a
provider problem, not a wrong answer: the report keeps errors out of the pass rate.

---

## 7. "Where do I change…?"

| I want to change… | Open | Then |
|:---|:---|:---|
| How the assistant answers (tone, citations, advice) | `features/chat/prompt.py` → `SYSTEM_PROMPT` | `python -m eval.eval_harness` |
| **Which lookups the LLM can use, or when it picks which** | `features/chat/tools.py` → `TOOLS` (descriptions are the instructions), `features/chat/agent.py` → `FETCHER_PROMPT` | evaluate |
| A new lookup (e.g. "votes by a wallet across DAOs") | `features/chat/tools.py` → write it, add to `FUNCTIONS` and `TOOLS` | `tests/test_tools.py` |
| How close a passage must be to count | `features/chat/tools.py` → `MAX_DISTANCE_*` | evaluate |
| Which numbers one proposal's facts contain | `features/chat/context.py` → `proposal_facts` | tests |
| A formula (silence ratio, whale share, …) | `features/metrics.py` | `python -m pytest` (pins the values) |
| The LLM providers or their order | `features/chat/llm.py` → `PROVIDERS` | `python -m features.chat.llm` |
| Which DAOs we follow | `config/curated_daos.py` | `--sync-all` |
| How wallets are linked to users | `features/identity/strategies/` | `python -m features.identity.runner --all` |
| Add a hand-verified wallet link | `features/identity/strategies/registry.py` → `KNOWN_DELEGATES` | `--all` |
| A table or column | `db/schema.py` (also add new columns to `ADDED_COLUMNS`) | restart / any command |
| An API endpoint | `features/<feature>/routes.py` | it appears in `/docs` and `/` automatically |

---

## 8. Words used in this project

| Term | Meaning |
|:---|:---|
| **Space** | A DAO on Snapshot, e.g. `ens.eth` |
| **Proposal** | One question put to a vote |
| **vp (voting power)** | How much weight a wallet's vote carries (usually tokens held or delegated) |
| **Silence ratio** | Forum posters ÷ voters, as %: how few voters explain themselves |
| **Top-4 share** | Share of all voting power held by the 4 biggest wallets: whale concentration |
| **Chunk** | A piece of text stored in ChromaDB: a block of proposal paragraphs, or a forum post (or part of a long one) |
| **Distance** | How far a chunk's meaning is from the query; lower is closer. Correct passages lie at about 0.2-0.85, passages for a question that is not about governance at 1.0 or more |
| **Context line** | The line put in front of a chunk before it is embedded (`Forum post by <author> on the proposal "<title>":`), so a question naming the person or the proposal can match. The stored chunk stays plain |
| **BM25 / keyword search** | Scores chunks by the exact words they share with the question; rare words count more. Finds names, tickers and numbers that a search by meaning misses |
| **Reranker** | A small model that reads the question and one passage together and scores how well the passage answers it; used to order the ~30 candidates the two searches found |
| **RAG** | Retrieval-Augmented Generation: find relevant text first, then let the LLM answer from it |
| **Tool calling** | The LLM replies with a *request* ("run `person(name=griff)`"); our code runs it and returns the result. The LLM never runs anything itself |
| **Agent / evidence** | Stage 1: the LLM that picks the lookups, and the list of lookups with their results that it collects |
| **Writer** | Stage 2: the single LLM call that writes the final answer from the evidence, under the answer rules |
| **DATABASE FACTS** | The lookup results (JSON) written into the writer's prompt above the sources |
| **[Background]** | Marks a sentence the model wrote from its own general knowledge (allowed for concepts, never for numbers, results or who voted). Excluded from the faithfulness score; tracked as *background share* |
| **Link confidence** | How sure a wallet ↔ username link is: low · medium · high (wallet voted in that DAO) · certain (hand-verified) |
| **Complete / partial / missing** | Whether we store all, some or none of what the source says exists |
| **Idempotent** | Running it twice gives the same result as once (no duplicates) |

---

## 9. Where to read more

- [README.md](README.md) — findings, API reference, setup, the Code Guide section
- [DATA_FLOW.md](DATA_FLOW.md) — diagrams of every flow, mapped to files
- Any `.py` file — its header, function notes, and "Where control goes next"
- [tests/](tests/) — each test names the behaviour it protects; reading them is a quick way to learn the rules
