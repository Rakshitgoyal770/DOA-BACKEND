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
- **The LLM never reads the database.** Our code reads SQL, turns the result into a few
  lines of text, and puts them in the prompt next to the retrieved passages.

---

## 2. Follow one chat question, file by file

Example: `POST /chat {"query": "Why did people support it?", "proposal_id": "0xe97a…" }` (DefiLlama).

| # | File | Function | What happens | Output |
|:-:|:---|:---|:---|:---|
| 1 | [main.py](main.py) | — | The request matches the `/chat` router | → routes |
| 2 | [features/chat/routes.py](features/chat/routes.py) | `chat` | Validates the body (`query` 3–2000 chars, `n_results` 1–20) | → `run_chat` |
| 3 | [features/chat/service.py](features/chat/service.py) | `run_chat` | Runs steps 4–8 in order. **Same function the evaluation uses.** | answer + sources |
| 4 | [features/chat/retrieval.py](features/chat/retrieval.py) | `retrieve` | Embeds the question, asks ChromaDB for the 5 nearest chunks *of this proposal*, drops any with distance > 0.7 | 5 chunks (text + metadata) |
| 5 | [features/chat/context.py](features/chat/context.py) | `enrich_chunks` | For each forum post: author → wallet → that wallet's vote on this proposal (live SQL) | `chunk["sql"]` |
| 6 | [features/chat/context.py](features/chat/context.py) | `collect_facts` | For each proposal behind the chunks (max 3): result, voters, posters, silence ratio, top-4 share | `facts` |
| 7 | [features/metrics.py](features/metrics.py) | `top_voter_share`, `silence_ratio_pct`, … | The formulas used in step 6 (the **same** ones the endpoints use) | numbers |
| 8 | [features/chat/prompt.py](features/chat/prompt.py) | `build_prompt` | Writes the system rules + facts block + numbered sources + question | 2 messages |
| 9 | [features/chat/llm.py](features/chat/llm.py) | `generate` | Tries Groq → Gemini → OpenRouter → Mistral until one answers | answer, provider |

**What the LLM actually receives (step 8):**
```
PROPOSAL FACTS (from the database):
- Optimism Collective | "Season 2: Cycle 8: DefiLlama" | state: closed
  result: For 91.7%; Against 1.4%; Abstain 6.9% (winner: For)
  voters: 14194; forum posters: 12 (silence ratio 0.085%)
  top 4 loaded voters hold 50.4% of total voting power

Sources:
[Source 1 - forum_post by OPUser (wallet link: low)] Glad to see you here...
[Source 2 - proposal_body] This Governance Fund Phase 1 proposal is eligible...

Question: Why did people support it?
```

**If something goes wrong:** no chunk close enough → HTTP 404 and the LLM is *not* called ·
invalid body → 422 · every LLM provider fails → 500.

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
| Opening the database (and upgrading its schema) | [db/schema.py](db/schema.py) `get_connection` | everything |
| Which DAOs we follow | [config/curated_daos.py](config/curated_daos.py) | proposal sync, `/daos` |

Change a rule in its home and every user of it changes together.

---

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
| See what data we have / what's missing | `python -m features.sync.runner --check` |
| Bring all data up to date | `python -m features.sync.runner --sync-all` |
| Backfill many votes or threads | `--fetch-votes --limit 200` · `--fetch-forum --limit 200` |
| Re-check wallet links (fast, offline) | `python -m features.identity.runner --upgrade` |
| Run every linking strategy (network, minutes) | `python -m features.identity.runner --all` |
| Update the search index | `python -m vector.embedding` (add `--dry-run` to preview) |
| Check my LLM keys work | `python -m features.chat.llm` |
| Run the tests | `python -m pytest` |
| Measure answer quality (LLM calls) | `python -m eval.eval_harness` |

---

## 7. "Where do I change…?"

| I want to change… | Open | Then |
|:---|:---|:---|
| How the assistant answers (tone, citations, advice) | `features/chat/prompt.py` → `SYSTEM_PROMPT` | `python -m eval.eval_harness` |
| How many / how close chunks are retrieved | `features/chat/retrieval.py` → `max_distance`, `n_results` | evaluate |
| Which numbers go into the facts block | `features/chat/context.py` → `proposal_facts`, `format_facts` | tests |
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
| **Chunk** | A piece of text stored in ChromaDB (a proposal paragraph block or one forum post) |
| **Distance** | How far a chunk's meaning is from the question; lower is closer; kept if ≤ 0.7 |
| **RAG** | Retrieval-Augmented Generation: find relevant text first, then let the LLM answer from it |
| **Facts block** | The SQL numbers written into the prompt above the sources |
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
