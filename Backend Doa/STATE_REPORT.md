# STATE REPORT — DAO Governance Intelligence

Audit date: 2026-11-12. Branch `feature/restructure-phase1`, HEAD `65e9bab`, working tree clean at start.
Mode: read-only. The only file created in the repo is this report.

**How I stayed read-only.** `get_connection()` and the FastAPI startup both run schema writes, and the real-DB tests call them. So I did **not** run anything against `db/dao_intelligence.db` or `chroma_data/` directly. I copied both into a scratchpad (SHA-256 of the DB copy equals the original; the original's hash and mtime were unchanged after the audit), and ran every query, the tests and the index dry-run on the copies. No LLM provider was called. The API keys were unset for the test run.

**Legend.** FACT = backed by output I ran, or by a file I read, with path and line. INFERENCE = my reading of code or data. UNKNOWN = not determinable.

---

## 0. Headline findings (read these first)

1. **FACT, security: all five live API keys are committed in git history, and the commit is on `origin/main`.** Commit `42fac17` (2026-09-26) added `Backend Doa/.env` with Groq, Gemini, OpenRouter, Mistral and Etherscan keys. I compared them by value with the current `.env` without printing them: all five are **identical** to the keys in use today. `origin/main` and `origin/feature/restructure-phase1` both contain that commit. Whether the GitHub repo is public is UNKNOWN (`gh` is not installed here). Rotate all five keys, whatever the visibility. See §6.
2. **FACT: the README's quality scores cannot be reproduced from any saved run.** The README badges and the resume bullet (README line 348) claim Faithfulness 90%, Context Recall 87%, Relevancy 100%. The only saved run with judge scores is unfinished: 8 of 38 cases judged, faithfulness 0.75, relevancy 0.91. The README itself says (lines ~113-116) the scores are from an earlier pipeline.
3. **FACT: there is no citation validation in code.** "[Source N] / [Facts]" citation is a prompt instruction only (`features/chat/prompt.py:57-58`). Nothing checks that the cited N exists or supports the claim.
4. **FACT: the "dash_*/dao_* cases fail" premise is out of date.** In the latest complete run (2026-10-27) 8 of the 9 dash/dao cases pass. Only `dao_arbitrumfoundation_closest` fails. Details in §4.
5. **FACT: Mistral is no longer a provider.** It was removed on purpose (commit `a891d2f`, `llm.py:32`). The chain is Groq → Gemini → OpenRouter. A Mistral key still sits in `.env`, but nothing uses it.
6. **FACT: the index is not cosine.** The Chroma collection uses `space: l2` (default), but code and README call the thresholds "cosine distance" (`retrieval.py:28`, `tools.py:50-56`). INFERENCE: the thresholds were tuned empirically, so retrieval works, but the label is wrong. The index also holds a stray hand-inserted test document (§2).
7. **FACT: the data is 3 weeks old.** DB fetched 2026-10-21/22; today is 2026-11-12. All 7 proposals stored as `active` had end dates between Oct 22 and Oct 26, so they are now closed and the DB still calls them "leading".

---

## 1. INVENTORY

### 1.1 Directory tree (2 levels, tracked files; 162 tracked files)

```
/                                  monorepo root
├─ README.md                       root readme (12 lines); calls Backend Doa/ "a copy ... reference only; the live backend is the separate Backend Doa project" (ambiguous/stale)
├─ package.json, package-lock.json, .oxlintrc.json   npm workspace + lint for frontend
├─ frontend/                       React/Vite/TS UI "Quorum" (src/api, components, pages, lib, hooks, context) — NOT audited beyond listing
└─ Backend Doa/
   ├─ main.py                      FastAPI app, CORS "*", router registration, startup init_db, health route "/"
   ├─ requirements.txt, pytest.ini
   ├─ README.md, GUIDE.md, DATA_FLOW.md   docs
   ├─ config/curated_daos.py       the 5 hand-picked Snapshot spaces + aliases
   ├─ db/schema.py                 all table DDL, migrations, get_connection()
   ├─ clients/                     snapshot.py (GraphQL paging), discourse.py (URL normalise + fetch), ens.py (ENS lookups)
   ├─ features/
   │  ├─ proposals/                fetch.py, service.py, routes.py   proposal ingest + REST
   │  ├─ votes/                    fetch.py, completeness.py          full vote ingest + completeness
   │  ├─ forum/                    fetch.py, completeness.py          Discourse ingest + completeness
   │  ├─ identity/                 runner.py, common.py, stats.py, routes.py, strategies/{ens_username,profile,self_disclosed,upgrade,voter_ens,registry}.py   username→wallet resolution
   │  ├─ sync/                     runner.py, audit.py, routes.py     orchestration + audit + POST /sync/run
   │  ├─ daos/                     service.py, routes.py              per-DAO stats
   │  ├─ metrics.py                the single home for formulas (silence ratio, top-N share, winners, choice decoding)
   │  └─ chat/                     agent.py, tools.py, retrieval.py, context.py, prompt.py, llm.py, service.py, routes.py, cli.py
   ├─ vector/                      chunking.py, embedding.py          chunking + incremental Chroma sync
   ├─ eval/                        golden_dataset.py, build_golden.py, golden_generated.json, checks.py, eval_harness.py  (results/ is gitignored)
   ├─ eXPlEARNING/                 tool_calling_basics.py + README     experiments, imported by nothing
   ├─ tests/                       15 test files, 239 tests
   ├─ db/dao_intelligence.db       untracked, 322 MB
   └─ chroma_data/                 untracked, 103 MB
```

One-line purpose per backend file: see the tree above and the module docstrings. Every module opens with a docstring that states its purpose. I read all of `llm.py`, `agent.py`, `tools.py`, `prompt.py`, `context.py`, `retrieval.py`, `service.py`, `routes.py` (chat), `main.py`, `db/schema.py`, `vector/*`, `eval/*`. I skimmed `sync/*` and `identity/routes.py`. I did not read the strategy files, `clients/*` or `proposals/*` line by line.

### 1.2 Unused, duplicated, or dead

| Item | Evidence | Verdict |
|---|---|---|
| Table `proposal_polling_state` | exists in the real DB (`sqlite_master`), 0 rows, with columns `is_active`, `last_requested_at`, `refresh_interval_minutes`. **Not defined in `db/schema.py`** and not referenced anywhere in HEAD | FACT: dead leftover from an abandoned polling design |
| `ETHERSCAN_API_KEY`, `MISTRAL_API_KEY` in `.env` | `git grep -i etherscan HEAD` returns nothing. Mistral only appears in comments, a test and a stale doc line | FACT: unused keys that are still live secrets |
| `GUIDE.md:205` | still says the `.venv` "has `groq` and `mistralai`" | FACT: stale doc |
| Chroma doc `zeptimus_post_1` | in the index, but its id does not match `proposal_*` or `forum_post_*`, so the sync never deletes it. The text is a "Voting FOR…" post on the Good Entry proposal, `source_type: forum_post` | FACT: stray manual test insert, retrievable as a real forum source |
| `eval/golden_generated.json` `needs` fields | e.g. "DAO scope + DAO SQL facts", "advice mode" — these features exist now | INFERENCE: stale labels. `print_report` shows them under "feature not built yet" |
| `requirements.txt` | lists both `google-genai` and `google-generativeai`; only `google.genai` and `openai` are imported by `llm.py` | INFERENCE: `google-generativeai` is dead and deprecated. `mistralai` is correctly absent |
| `main.py:79` `@app.on_event("startup")` | pytest warns it is deprecated in this FastAPI | FACT |
| Unreferenced top-level functions | An AST scan of all non-test, undecorated top-level functions and classes (docstrings stripped) found none unreferenced | FACT: no dead top-level functions found. Route handlers are excluded because they are decorated |
| Duplicated rows | forum posts are stored once per proposal that links the thread (`schema.py:32-37`) | FACT, by design: this causes 333 duplicate chunk texts in Chroma, see §2 |
| `eXPlEARNING/` | imported by nothing | FACT: experiment folder, harmless |
| Root `README.md` vs `Backend Doa/` | root README says Backend Doa is "a copy ... reference only" | INFERENCE: confusing leftover from the monorepo move |

### 1.3 Added since the original plan (ingestion, resolution, vector, agent, eval)

Reasons are INFERENCE from commit messages and docstrings.

- **Sync runner and audit** (`features/sync/*`, `GET /sync/status`, `POST /sync/run`, commit `a4034c0`): the data needed re-fetching and a completeness check.
- **Vote and forum completeness** (`votes/completeness.py`, `forum/completeness.py`, commits `e239490`, `9140e3a`): earlier versions capped votes at 500-1,000 per proposal, and the README admits a wrong concentration finding as a result.
- **`features/metrics.py`** (commit `5f8776e`): "one home for every formula", so chat, API and golden set agree.
- **ENS client and `wallet_ens` cache**: identity strategies `voter_ens`, `ens_username` and `profile`.
- **`self_disclosed` and `upgrade` strategies** (commit `3404c0d`): accept a self-claimed wallet only when "claimed as own".
- **`vector/chunking.py`** (commit `cd6d980`): 17% of forum posts exceeded the 512-token limit.
- **Two-stage tool-calling agent** (`agent.py`, `tools.py`, commit `886149c`) replaced "vector search picks the facts". The old design ranked from 2-3 retrieved proposals.
- **Terminal chat CLI** (`features/chat/cli.py`).
- **Golden-set builder** (`build_golden.py`), plus eval `--resume` and `--regrade`.
- **REST routes** for proposals, DAOs and identities, a **frontend**, and **docs** (`GUIDE.md`, `DATA_FLOW.md`).
- **Provider changes**: Mistral removed (`a891d2f`); `groq-small` and the OpenRouter model list added.

---

## 2. DATA STATE (all queries run on the byte-identical copy; scripts in the scratchpad)

### 2.1 Row counts (FACT)

```
spaces 5 | proposals 118 | votes 515606 | forum_posts 2398 | forum_threads 110
resolved_identities 82 | wallet_ens 698 | proposal_polling_state 0 (undeclared table)
```

### 2.2 Per DAO (FACT)

| space | proposals | with discussion_url | votes ingested (proposals/rows) | with forum posts (proposals/rows) | states (closed/active) |
|---|---:|---:|---|---|---|
| aavedao.eth | 31 | 31 | 31 / 2,624 | 31 / 214 | 29 / 2 |
| arbitrumfoundation.eth | 24 | 24 | 24 / 30,517 | 24 / 534 | 20 / 4 |
| ens.eth | 21 | 20 | 21 / 2,074 | 19 / 529 | 20 / 1 |
| opcollective.eth | 20 | 19 | 20 / 475,501 | 19 / 824 | 20 / 0 |
| uniswapgovernance.eth | 22 | 21 | 22 / 4,890 | 20 / 297 | 22 / 0 |
| **total** | **118** | **115** | **118 / 515,606** | **113 / 2,398** | 111 / 7 |

- Spaces on Snapshot hold 1,803 proposals (423 + 989 + 93 + 199 + 99), so we hold **6.5%** of them: the most recent 20-31 per DAO.
- **Vote completeness:** stored votes equal `proposals.votes_count` for **118 of 118** proposals (sum 515,606 = 515,606), with no duplicate (proposal, voter) pairs.
- **Proposals with a link but no posts (2):**
  - a Uniswap proposal, whose thread returns 404 (`forum_threads.last_error`);
  - an ENS proposal, whose `discussion_url` is a gist `manifest.json`, not a forum thread. That is bad source data.
- **Proposals with no discussion_url (3):** one Optimism, one Uniswap, one ENS.
- `scores_state`: 111 final, 7 pending (those are the 7 active ones).
- README drift: the table says ENS has 20 proposals; the DB has 21.

### 2.3 Chroma (FACT; collection `dao_chunks`, `chroma.sqlite3` mtime 2026-11-08 12:16)

- **5,902 chunks**: `forum_post` 5,196 and `proposal_body` 706. Per DAO: opcollective 1,312 + 20, arbitrum 1,090 + 234, ens 1,043 + 160, aave 1,029 + 181, uniswap 722 + 111.
- **Embedding model: `BAAI/bge-small-en-v1.5`, 384 dimensions.** It is defined only in `vector/embedding.py:39`. The index does not record the model. Its stored `embedding_function` is Chroma's default (MiniLM-class, also 384-d). INFERENCE: this is safe today because `retrieval.py:31-35` passes its own `query_embeddings`. A future `query_texts=` call would silently embed with the wrong model.
- **Distance metric: `l2` (`hnsw.space`)**, not cosine. See §0.6.
- **Metadata keys present:** `proposal_id` (5,902), `source_type` (5,902), `author` (5,196), `resolved_wallet` and `confidence_level` (1,315), `voting_power` (1,007), `title` and `space_id` (706). **Forum chunks carry no `space_id`.** `tools.py:257` works around this by filtering on proposal-id lists.
- **Forum chunks with `voting_power`: 1,007 of 5,196 (19.4%)**. With a resolved wallet: 1,315 (25.3%).
- **Sync state:** `python -m vector.embedding --dry-run` (offline) printed `{'documents': 5901, 'embed': 0, 'update_metadata': 0, 'delete': 0, 'unchanged': 5901}`. The index matches SQLite exactly, plus 1 extra doc, the stray `zeptimus_post_1` (5,902 vs 5,901).
- **Duplicates:** 5,569 distinct texts across 5,902 chunks, so **333 extra copies**:
  - 312 forum chunks duplicated across proposals (shared threads);
  - 16 forum chunks duplicated within the same proposal;
  - 5 proposal-body chunks duplicated across proposals.
  - Note: `split_evidence` (`prompt.py:166-192`) dedupes identical passages at answer time.
- **No empty chunks.**
- **Orphans:** 0 chunks reference a proposal missing from SQLite.

### 2.4 Resolution (FACT)

- Distinct forum usernames: **475** (472 case-insensitively). The 3 case-variant pairs are why the two numbers differ.
- `resolved_identities`: **82 rows, all with a wallet; there are no `unresolved` rows stored.** So **82 of 472 (17.4%)** usernames resolve, and **393 distinct usernames are unresolved**. Unresolved is implicit (absent), not recorded.
- By confidence and method:

| confidence | method | n |
|---|---|---:|
| medium | ens_username | 26 |
| high | voter_ens | 24 |
| high | ens_username | 19 |
| high | profile_ens | 6 |
| medium | profile_ens | 3 |
| certain | registry | 1 |
| high | ens | 1 |
| high | self_disclosed | 1 |
| medium | voter_ens | 1 |

- **By tier: certain 1, high 51, medium 30, low 0.**
- Posts by author tier: certain 32, high 534, medium 111, unresolved 1,721 of 2,398 posts. **71.8% of forum posts have no wallet.**
- No wallet is linked to two usernames. `wallet_ens`: 698 rows, 531 verified, 165 with no name.
- **Rows with a resolved wallet that also voted on the same proposal** are the source of `voting_power` metadata (1,007 chunks). I did not count this separately; the SQL join was too slow on 515k rows and I killed it. The Chroma figure above is the real measure.

### 2.5 Empty / NULL fields (FACT)

- `proposals.discussion_url`: 3 NULL. Every other proposal column is complete.
- `forum_posts.content`: **70 empty strings** (Optimism 58, ENS 8, Aave 3, Arbitrum 1). The index skips them. Post bodies range from 0 to 58,837 characters.
- `spaces.about`: 2 empty.
- `votes`: no NULL or empty voter, choice, vp or timestamp; no zero or negative vp.
- `forum_posts`: 20 (proposal, text) groups are exact duplicates of each other within a proposal.

---

## 3. PIPELINE STATUS

Evidence note: the saved eval run (§4) predates the last code commits by an unknown amount (see §4), so "generation" rests on tests plus an older-dated run. I did not run live network ingestion or any LLM call.

| Stage | Status | Evidence |
|---|---|---|
| **Ingestion** (Snapshot, votes, Discourse) | **WORKS, with caveats** | DB state: 118 proposals, 515,606 votes (118/118 complete), 113/115 linked threads fetched. `pytest` passed `test_votes.py` (8), `test_forum.py` (14), `test_proposals.py` (11), `test_snapshot_paging.py` (5). **Not re-run live** (it would call Snapshot/Discourse and write to the DB). Caveats: data is stale since 2026-10-22; 1 thread 404s; 1 `discussion_url` is not a forum link; only 6.5% of each space's proposals are held |
| **Identity resolution** | **PARTIAL** | Runs and persists (82 links, §2.4). Only 17.4% of usernames resolve and 71.8% of posts have no wallet. Only `self_disclosed` has tests (`test_self_disclosed.py`, 10 tests). The `ens_username`, `profile`, `voter_ens` and `registry` strategies and `clients/ens.py` have no tests |
| **Chunking** | **WORKS** | `pytest tests/test_chunking.py` passes (9), including the real-data "no chunk over 512 tokens" test per the docstring. Index shows 5,196 forum chunks from 2,328 non-empty posts |
| **Embedding / index sync** | **WORKS** | The offline dry-run on the copy printed the all-unchanged result in §2.3. `test_embedding_sync.py` passes (9). The one stray doc is a defect (§1.2) |
| **Retrieval** | **WORKS, mislabelled** | `retrieval.py` plus `tools.search_forum` with metadata scoping (proposal, author, source_type, DAO via an id list). Tested only through fakes (`test_tools.py:188` monkeypatches `retrieve`). `retrieve()` itself has no direct test. `test_golden.py:113` checks that every expected source id exists in the real index (passed). Distance is L2 with thresholds 0.7 / 0.85 / 1.0 (`tools.py:54-56`) |
| **Routing (SQL / RAG / both)** | **PARTIAL (different design from "a router")** | There is **no deterministic router.** The LLM picks among 7 lookups through tool calling (`agent.py`, `tools.py:312-353`). A regex safety net adds a forum search for "why / opinion" questions (`agent.py:170-177`). So routing quality depends on the model. The eval shows it routing correctly in the most recent run (§4) |
| **Prompt building** | **WORKS** | `prompt.py` builds system + user messages with facts, sources and advice mode. `test_prompt.py` passes (45) |
| **Generation** | **WORKS (by saved run + tests)** | Latest complete run: 35 of 38 passed (2026-10-27, `run_20261027_160401.json`). Providers during that run: openrouter 29, groq 7, gemini 2. Fallback tests pass (`test_chat_service.py`, 17). Live provider health is UNKNOWN (not called) |
| **Citation validation** | **NOT BUILT** | `grep -i citation` finds only prompt text and docstrings. Nothing parses `[Source N]` or `[Facts]` in an answer. The only automatic check on citations is the optional LLM faithfulness judge, which is not run by default |
| **API layer** | **WORKS (tests only; server not started live)** | 27 tests in `test_regression_real_db.py` passed on the copy, including `GET /` plus read endpoints returning 200, 404 cases, and `POST /chat` with a stubbed pipeline. `/chat` end to end with real providers: not run. Gaps in §6/§7: no auth, CORS `*`, public write endpoints |

**Command and output, tests.** Run as `python -m pytest -p no:cacheprovider -rs -q` in the scratchpad copy, keys unset. `pytest.ini` has `addopts = -q`, so `-q` doubles up and no summary line prints. Raw output was 239 dots across four lines, then warnings, then `exit=0`. `--co` collected 239 tests (counts per file in §5).

---

## 4. EVAL

### 4.1 Golden dataset (FACT)

- **38 cases** = 5 hand-written (`CURATED`, `golden_dataset.py:38-82`) + 33 generated (`golden_generated.json`, `generated_at 2026-10-23T07:06:45`).
- Generated levels / intents: dashboard (compare, overview, record), dao (closest 2, coverage 2, recent 2), proposal (concentration 2, explain 2, posters 2, result 2, result_unscoped 1, turnout 2), detail (author_vote 2, who_said 2, ranked_vote 1), behaviour (advice 2, ambiguous, background, mixed, nonexistent, out_of_scope, unanswerable).
- Expected behaviours: answer 25, say_insufficient 3, no_recommendation 2, background_tagged 2, ask_clarify 1 (generated cases only). **8 cases are `volatile`**, so they need regenerating after any sync.
- **Who wrote the ground truth:**
  - the 33 generated cases: **code** (`build_golden.py`), which reads the DB and computes expected numbers with raw SQL, deliberately not `features/metrics.py`;
  - the 5 curated cases: hand-written. The author is UNKNOWN from the repo; all commits are by `Rakshitgoyal770`.
- **`ground_truth_context_ids`** is called `expected.sources` here.
  - Filled in for **5 curated + 4 of the 33 generated = 9 of 38** cases. The other 29 have empty sources and so are not retrieval-checked: `check_sources` returns "pass, recall 1.0" when the list is empty (`checks.py:119-120`). The saved runs' average recall (0.94) is therefore inflated.
  - **Verified:** `test_golden.py::test_every_expected_source_exists_in_the_search_index` (passed) checks the ids exist in the index. `test_stable_expected_numbers_agree_with_the_apps_own_formulas` (passed) checks the numbers against the app's formulas. Neither checks that the source actually contains the answer; there was no human relevance review that I can see.
- Eval is **heavily Good-Entry/Optimism-flavoured for curated cases**: 1 Arbitrum Good Entry and 4 Optimism proposals. See §7.

### 4.2 Generator and judge models

- **Neither is pinned.** The generator is `generate()` and the agent is `generate_with_tools()`, both walking a fallback chain (`llm.py:110-114`, `195-196`). The judge is the **same chain** (`eval_harness.py:87` and `checks.py:153` call `generate`). The fallback can swap the generator or judge **mid-run, even mid-case.**
- FACT from the latest complete run: providers per case were openrouter 29, groq 7, gemini 2. The "pass rate" mixes three different model families.
- Models hardcoded: Groq `openai/gpt-oss-120b` (env-overridable only for the tool agent via `GROQ_TOOL_MODEL`), Groq `openai/gpt-oss-20b`, Gemini `gemini-3.6-flash`, and 4 OpenRouter `:free` models (`llm.py:57, 70, 83-88, 167, 174, 190`).
- Nothing in the results file records which model produced an answer, only the provider name. OpenRouter alone is 4 different models.

### 4.3 How 429 / quota errors are scored

- **Single provider 429:** the chain silently falls back (printed to stdout only, `llm.py:132`, not saved in results). It is invisible in the scores.
- **All providers fail inside `run_chat`:** the case is recorded `error: true`, **excluded from the pass rate**, listed separately (`eval_harness.py:157-160, 200-205`). It is ERROR, not FAIL. FACT: 4 such error cases in saved results, including `dao_arbitrumfoundation_closest` hitting Gemini 429 three times (`run_20261027_164246/164414/164437.json`), and a Gemini `thought_signature` 400 in `run_20261027_152233.json`.
- **Judge failure (INFERENCE from reading `eval_harness.py:156-164`):** `run_case` only wraps `run_chat` in `try`. `grade()` → `check_behavior()` → `generate()` and the `--judge` scoring are outside it. If every provider fails there (e.g. quota exhausted while judging), the exception propagates and **aborts the whole run**. I did not execute this path.
- **Side effect (INFERENCE):** because errors leave the denominator, a run with many ERRORs can look better than it is.

### 4.4 Caching and saved results

- **No answer cache.** There is **`--resume`** (reuses answered cases of an unfinished file) and **`--regrade`** (rescoring saved answers with zero LLM calls). Results are rewritten after every case.
- Saved results: 24 files in `eval/results/` (gitignored). Many are partial or small `--only` runs.
- **Latest complete run: `eval/results/run_20261027_160401.json`, 2026-10-27, 38 of 38 finished, 0 errors, 35 passed (92.1%).**
  - Fails: `dao_arbitrumfoundation_closest`, `prop_explain_opcollective`, `detail_ranked_vote`.
  - The same dataset over time: 9 → 23 → 27 → 28 → 32 → 35 (runs from Oct 22 to Oct 27).
- **Whether it reflects HEAD is UNKNOWN.** Commits `886149c`..`cc26021` (agent, chunking, passage dedupe) are timestamped 2026-11-07; the newest result is 2026-10-27. The runs may predate that code or the commits may be a late batch. The index was rebuilt on 2026-11-08.

### 4.5 Latest scores per metric

| Metric | Latest value | Date, file |
|---|---|---|
| Exact-check pass rate | **35 of 38 = 92.1%** | 2026-10-27, `run_20261027_160401.json` |
| Average retrieval recall (inflated, see 4.1) | **0.94** | same file |
| Faithfulness (judge) | **none from a complete run.** Only partial: 0.75 over 8 judged answers | `run_20261023_001111.json`, unfinished, 2026-10-23, older pipeline |
| Answer relevancy (judge) | **none from a complete run.** Only partial: 0.91 over 8 judged answers | same file |
| Background share | **none** (judged runs only) | — |
| Context precision | **none** (README quotes 0.21, no source file) | — |

### 4.6 Why the `dash_*` and `dao_*` cases fail (FACT, by file and case)

In the latest complete run (`run_20261027_160401.json`), 8 of 9 pass. The older complete run, `run_20261024_163628.json`, had 3 dash fails and 0 dao fails. So this is no longer a systemic problem.

| Case | Latest run | Cause (reading the failure line) |
|---|---|---|
| `dao_arbitrumfoundation_closest` | **FAIL** (openrouter) | answer lacked winner share 66.7 and the title "Continued Funding for the Arbitrum Foundation". INFERENCE: wrong "closest" answer from a weaker OpenRouter model, or a changed ranking after the sync; not retrieval (recall 1.0), not missing data. Re-runs of this case on 2026-10-27 then died with Gemini 429, so it was never re-confirmed |
| `dash_compare_silence` | pass (groq) | In the 10-24 run it failed `number missing: silence %=11.549` (wrong or reformatted number) |
| `dash_record_turnout` | pass (gemini) | In the 10-24 run: missing 63,845 voters and the title `Special Voting Cycle #9b` |
| `dash_overview_recent` | pass (openrouter) | In the 10-24 run: 3 recent titles missing (the "newest proposals" were not listed) |
| other 5 `dao_*` | pass | — |

Cause class, FACT from the failure lines: number or title missing from the answer, with recall 1.0 in each. **None are quota failures or missing data.** INFERENCE: routing (SQL lookup chosen or not) and model quality drove the earlier failures.

---

## 5. TESTS

**Run (on the scratchpad copy; keys unset; no network by design):** 239 collected, **239 passed, 0 failed, 0 skipped** (raw output was only dots, exit code 0; counts add up: 19 + 3 + 17 + 9 + 9 + 14 + 17 + 9 + 45 + 11 + 27 + 10 + 5 + 36 + 8 = 239).

| File | n | File | n |
|---|---:|---|---:|
| test_prompt | 45 | test_chat_service | 17 |
| test_tools | 36 | test_golden | 17 |
| test_regression_real_db | 27 | test_forum | 14 |
| test_agent | 19 | test_proposals | 11 |
| test_self_disclosed | 10 | test_chunking | 9 |
| test_metrics | 9 | test_embedding_sync | 9 |
| test_votes | 8 | test_snapshot_paging | 5 |
| test_chat_cli | 3 | | |

Caveats:
- The `real_db` tests (27) are only meaningful because I gave them a copy. They need the 322 MB DB and, via `test_golden`, the Chroma index.
- Running them in the repo would write to the real DB (`TestClient(app)` startup runs `init_db`; `get_connection` runs `_ensure_schema`). The test module's own docstring admits "opening a connection may create missing indexes".

**Important logic with no tests (INFERENCE, from grepping which modules tests import; approximate):**
- Identity strategies `ens_username`, `profile`, `voter_ens`, `registry`; `clients/ens.py`; `identity/routes.py` including `POST /identities/resolve`.
- `features/sync/routes.py` (`POST /sync/run`), `proposals/routes.py` and `daos/routes.py` beyond the GET smoke tests.
- `retrieval.retrieve()` against a real index, with a real model.
- A live `POST /chat` with real providers; provider health.
- `eval/build_golden.py` (its output is indirectly checked by `test_golden`).
- The judge path inside `run_case` (see §4.3).
- **Citation correctness**: not built, so not tested.
- **The frontend**: it has Vitest files (`frontend/src/**/*.test.ts`) but I did not run them.

---

## 6. SECURITY AND CONFIG

### 6.1 Committed secrets (FACT)

- **`Backend Doa/.env` was committed.** Commits touching a root or Backend `.env`: `3e983a3` (2026-09-18), `e6ba9a8`, `b76236e`, `e125915` (09-18), `42fac17` (09-26), `a4034c0` (10-11). Only an Etherscan key appears in the early ones.
- **Commit `42fac17` (2026-09-26) added 5 keys**, by value:

| Variable | Length | Value identical to the current `.env`? |
|---|---:|---|
| GROQ_API_KEY | 56 (`gsk_` format) | **YES** |
| OPENROUTER_API_KEY | 73 (`sk-or-v1-` format) | **YES** |
| GEMINI_API_KEY | 53 | **YES** |
| MISTRAL_API_KEY | 32 | **YES** |
| ETHERSCAN_API_KEY | 34 | **YES** |

- **`origin/main` and `origin/feature/restructure-phase1` contain that commit**; remote is `https://github.com/Rakshitgoyal770/DOA-BACKEND.git`. Repo visibility: UNKNOWN. Rewriting history does not undo exposure if the repo was ever public or cloned.
- Pattern search of added lines across all history found exactly two key-shaped strings (a `gsk_` one and an `sk-or-v1-` one), both in `42fac17`'s `.env`. I found no `AIza`-prefixed string via that pattern (the Gemini key has a different shape), no `sk-ant`, `ghp_`, `AKIA` or `xox` hit. Long-hex search of HEAD: the only 64-hex strings are proposal ids.
- I did **not** print any secret value. Only lengths, prefix shapes and an equality check appear here.

### 6.2 Ignore and tracking state (FACT)

- `Backend Doa/.gitignore` ignores `.env`, `db/*.db`, `chroma_data/`, `.venv/`, `eval/results/`. At HEAD, tracked: only `frontend/.env.example` (no secrets, just a URL). The root `.gitignore` has no `.env` rule (the backend one covers it).
- **Past commits contain the DB and the index:** `db/dao_intelligence.db` and all `chroma_data/*` files were committed in `3e983a3`..`d603724` (Sep 18 to Oct 11). That is why the git pack is **41 MB**, and the data is recoverable from history. They are untracked now.
- History also held `scripts/check_chroma.py` and `vector/test_chroma.py`, deleted since.
- A `.pyc` set was tracked and removed in `fc5e801`.

### 6.3 Keys in logs or scripts (FACT)

- No `print(...)` of a key anywhere (`grep print(.*key|token` found nothing).
- `llm.py:132` and `248` print provider error text. A provider's error body could in principle echo request data, but I saw no key in any saved result's error text. UNKNOWN beyond that.
- Tests use `monkeypatch.setenv(..., "x")` dummies, not real keys.
- `eXPlEARNING/tool_calling_basics.py:34` reads the env var. Good.
- Eval result JSONs are gitignored and contain answers and errors only.

### 6.4 API exposure (FACT from `main.py` and the route list)

- **No authentication anywhere.** `allow_origins=["*"]` (`main.py:62`, commented "restrict in production").
- **`POST /sync/run`** (calls Snapshot and Discourse and writes the DB) and **`POST /identities/resolve`** (writes `resolved_identities`) are public.
- **`POST /chat`** can burn free-tier LLM quota with no rate limit. Pydantic bounds query length (3-2000) and `n_results` (1-20).
- SQLite is opened per request with no pooling. INFERENCE: concurrency on `POST /sync/run` plus reads is untested.

---

## 7. KNOWN ISSUES AND RISKS

**TODO/FIXME/HACK/XXX:** `git grep` over `*.py`, `*.ts`, `*.tsx` found **none**. The known-issue notes are in prose docstrings instead.

**Bugs and defects found (FACT unless marked):**
1. All 5 keys are in git history (§6.1).
2. Stray Chroma doc `zeptimus_post_1` (Good Entry) is retrievable as a real source (§1.2).
3. The data is stale; 7 proposals shown as active have ended (§0.7). The writer's prompt tells the model to say "as of our latest data", which only partly covers this.
4. Distance labelled cosine, actually L2 (§0.6).
5. One proposal's `discussion_url` is a gist `manifest.json` (ENS EP 6.10), and one Uniswap link 404s.
6. Eval denominator excludes errors, and 29 of 38 golden cases have no `expected.sources`, which inflates recall (§4.1, §4.3).
7. README and resume claims (90% / 87% / 100%) are unsupported by any saved complete run (§0.2).
8. INFERENCE: a judge failure aborts an eval run (§4.3).
9. `proposals.votes_count` is trusted as the total. For `active` proposals the stored vote set is a snapshot that cannot be complete later.
10. Only 17.4% of forum users resolve to a wallet. Answers about "who voted how" therefore cover a minority of posters. The prompt flags low-confidence links. INFERENCE: this is a coverage limit, not a bug.

**Hardcoded values:**
- **Models:** `llm.py:57, 70, 83-88, 167, 174, 190`; embedding model `vector/embedding.py:39`.
- **Thresholds:** retrieval distances 0.7 / 0.85 / 1.0 (`tools.py:54-56`), `retrieve()` default 0.7 (`retrieval.py:19`), chunk limits 1500 / 1200 / 500 tokens (`chunking.py:62-64`), `MAX_ROUNDS` 6, `MAX_SEARCHES` 2, `MAX_LOOKUPS` 6 (`agent.py:53-55`), `MAX_SOURCES` 8, `MAX_SOURCE_CHARS` 2000 (`prompt.py:50-52`), `RETRY_MAX_SECONDS` 15, `LLM_TIMEOUT_SECONDS` 45 (`llm.py:47-48`), top-4 "whale" share (`context.py:35`), "closest" excludes proposals with more than 3 options (`tools.py:147`).
- **Proposal ids:** none in non-test application code. The 5 curated golden cases, one regression test and 3 README mentions hardcode 5 real proposal ids.
- **DAO list:** `config/curated_daos.py`, plus the literal "all 5 DAOs" in `tools.py:155` and in the DAO aliases in the tool descriptions (`tools.py:307`).
- **Scope text:** "the most recent ones of each DAO, not their full history" is baked into `list_proposals` output (`tools.py:155-157`).

**Only works for the Good Entry example?** No for the pipeline: the DB, index and 5 DAOs are general, and 33 of 38 eval cases are generated across all 5 DAOs. But Good Entry leaks in through:
- the stray `zeptimus_post_1` Chroma doc (an Arbitrum Good Entry thread post);
- the curated case `cur_arbitrum_watchdog` (Good Entry / Watchdog);
- a Discourse URL for the Watchdog thread in `clients/discourse.py:212` (a `__main__` demo, INFERENCE);
- README examples.

**Free-tier and model-name dependencies:**
- All three providers are free tiers. The code and docs cite Groq's roughly 200,000 tokens/day on the big model and Gemini's roughly 20 requests/day (`llm.py:187-190, 19`), and OpenRouter's about 50/day. These numbers come from comments, not from anything I verified.
- Every OpenRouter model is `:free`, and the code comment says "three of the four we listed earlier stopped being free" (`llm.py:78-80`). **Expect these to break again.** The repo ships a checker (`python -m features.chat.llm --openrouter`) that I did not run, because it makes a network call.
- `gemini-3.6-flash`, `openai/gpt-oss-120b/20b` and the four OpenRouter ids may be renamed or retired. I did not verify that they currently exist. UNKNOWN.
- Gemini rejects mid-conversation tool history (`thought_signature` 400), worked around by flattening (`llm.py:198-223`). It is an upstream-behaviour dependency.
- A full 38-case run took about 1,358 s of recorded case time, at 2-6 LLM calls per case. Judged runs add 3 more calls per case.

---

## 8. WHAT I DID NOT VERIFY

| Claim | Why not |
|---|---|
| Live ingestion from Snapshot / Discourse still works | would hit external APIs and write the DB; judged against the read-only brief |
| Any LLM provider is currently reachable, or that the models still exist | no API quota spent, as instructed |
| `/chat` end to end, in a live server with real providers | same reason; the server was not started |
| The latest eval run reflects HEAD's code | no timestamp tying run to commit (commits are 11-07, run is 10-27) |
| That the golden set's 5 hand-written cases were written by a human, and by whom | the repo records only the committer |
| GitHub repo visibility, or whether anyone cloned it | `gh` is not installed; no web access used |
| That the committed keys are still valid/active at the providers | testing them would call the providers |
| Frontend behaviour, builds, tests | outside the pipeline scope; not run (`node_modules` present at the root, tests not executed) |
| Strategy-level resolution correctness (wallet links are right) | I only counted rows; no ground truth is available |
| Thresholds 0.7 / 0.85 / 1.0 fit the L2 scale | I read the comments; I did not re-measure distances |
| The SQL join of resolved wallets and votes on the same proposal | the query ran too long on 515k rows and I killed it |
| README findings (e.g. 86,445 voting wallets, median top-4 share 53.7%) | I checked only that distinct wallets is 86,446 (case-insensitive) and the 472 forum participants; the concentration medians are not recomputed |
| Test-gap list | derived from loose grep of imports; some modules may have indirect coverage |
| `requirements.txt` pins install and resolve | I used the existing `.venv` (Python 3.14.6); I did not reinstall |

---

## 9. REMAINING WORK (ordered by dependency)

### (a) Blocks everything else
1. **Rotate all five keys** (Groq, Gemini, OpenRouter, Mistral, Etherscan); delete the unused Mistral and Etherscan keys; then purge `.env`, the DB and Chroma from history (`git filter-repo` or BFG) and force-push, after confirming no one else relies on the old history. **Small to medium.**
2. **Refresh the data**: run `sync --sync-all`, `identity --upgrade`, `vector.embedding`, then regenerate `golden_generated.json` (volatile cases). The 7 "active" proposals and `scores_state` are wrong now. **Small** (runtime-bound).
3. **Delete the stray `zeptimus_post_1`** from Chroma and drop or decide on the `proposal_polling_state` table. **Small.**
4. **Pin and record the generator and judge** in the eval: fixed model per run, saved with each result, and no silent fallback during a scored run. **Medium.**

### (b) Quality
5. Run a **complete, judged eval** (`--judge`) on HEAD and keep the file. Then fix or remove the README badges and resume bullet. **Small** (quota-bound).
6. **Build citation validation**: parse `[Source N]` / `[Facts]`, check each N exists and that cited facts appear in the evidence, and report an unsupported-citation rate. **Medium.**
7. **Fill `expected.sources`** for the 29 cases that lack it, and have a human check relevance of the ground truth. **Medium.**
8. Make the judge path fault-tolerant (judge errors → ERROR, not an aborted run) and count provider swaps in results. **Small.**
9. **Raise identity coverage** beyond 17.4% of usernames; record `unresolved` explicitly instead of leaving rows absent. **Medium to large.**
10. **Tests** for the untested identity strategies, `clients/ens.py`, `retrieve()` on a real index, the judge path, and the write endpoints. **Medium.**
11. Fix the distance semantic: either create the collection with cosine and re-embed, or relabel and document L2. Add `space_id` to forum chunk metadata. **Medium.**
12. Clean the data: the ENS gist `discussion_url`, the Uniswap 404 thread, and the 70 empty posts. **Small.**
13. Remove stale docs and deps (`mistralai` in GUIDE.md, `google-generativeai`, golden `needs` labels, root README wording). **Small.**

### (c) Product
14. Cover more of each DAO's history (6.5% held), with a scheduled incremental sync. **Medium.**
15. Optional deterministic router or guard in front of the LLM tool choice for ranking / count questions. **Medium.**
16. Show data freshness in answers and UI (last-sync time; flag proposals that ended since the last sync). **Small.**
17. Finish or cut the frontend scope; verify it against the real API. **Medium.**

### (d) Deployment
18. **Auth and rate limiting** on `/chat`, `/sync/run` and `/identities/resolve`; restrict CORS; move writes behind a job or admin key. **Medium.**
19. Replace free-tier providers with paid or pinned ones, plus monitoring and alerts for provider failure. **Medium.**
20. Move SQLite and Chroma to managed or persistent storage (the README says Postgres is feasible); use FastAPI lifespan instead of `on_event`; CI running the 239 tests; container and secrets management. **Large.**
