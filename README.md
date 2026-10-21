# DAO Governance Intelligence Engine

> **Autonomous multi-source intelligence engine linking on-chain voting power to off-chain forum deliberation across decentralized autonomous organizations (DAOs).**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-red.svg)](https://www.trychroma.com/)
[![RAG Evaluation](https://img.shields.io/badge/Faithfulness-90%25-brightgreen.svg)]()
[![Context Recall](https://img.shields.io/badge/Context_Recall-87%25-brightgreen.svg)]()

---

## 1. Executive Summary & Problem Statement

Decentralized governance suffers from a fundamental information asymmetry:
1. **On-Chain Voting (Snapshot / Smart Contracts):** Highly structured, immutable, and exact — but completely silent regarding rationale or deliberation.
2. **Off-Chain Forums (Discourse):** Rich in arguments, dissent, and delegate commitments — but disconnected from actual voting weight.

**The Result:** Proposals pass or fail without transparency into whether the deciding voting power ever engaged with community concerns.

**DAO Governance Intelligence** bridges this divide by joining on-chain voter weight with forum discourse through fuzzy entity resolution, dense vector indexing, and an evaluated Retrieval-Augmented Generation (RAG) pipeline with resilient multi-provider LLM fallback.

---

## 2. Key Empirical Findings (Proven on Real Data)

This system was tested against live data from **5 major DAOs** (Optimism, Arbitrum, Aave, Uniswap, ENS) covering **117 proposals**, **515,000+ on-chain votes** and **2,300+ forum posts** (every vote and every post of each linked thread fetched, not a sample):

### 📊 The "Silence Gap" (Voters vs. Forum Deliberators)
Across the dataset there are **472 distinct forum participants** against **86,445 distinct voting wallets** — about **0.55%**, fewer than **1%** (an upper bound, since one person can hold several wallets):

| DAO Space | Proposals | Forum Coverage | Avg. Voter-to-Forum Ratio | Key Phenomenon |
|:---|:---:|:---:|:---:|:---|
| **Optimism Collective** (`opcollective.eth`) | 20 | **95.0%** | **0.111%** | 63,845 voters vs. 17 forum posters on election proposals |
| **Arbitrum DAO** (`arbitrumfoundation.eth`) | 24 | **100.0%** | **1.272%** | High community discussion, small voting cohort |
| **Aave DAO** (`aavedao.eth`) | 31 | **100.0%** | **6.853%** | Strict forum mandate before on-chain execution |
| **Uniswap** (`uniswapgovernance.eth`) | 22 | **90.9%** | **4.501%** | Heavy reliance on off-chain delegate statements |
| **ENS** (`ens.eth`) | 20 | **90.0%** | **11.626%** | Small, active technical community |

*Forum coverage = share of proposals with at least one forum post. The ratio is the average over proposals of forum posters ÷ voters, so a proposal with very few voters moves it a lot (e.g. Aave fell from 15.6% when one proposal grew from 1 voter). Earlier versions counted only the first 20 posts of each thread; these figures use every post.*

### 🐋 Whale Power Concentration
Measured on complete vote data (116 proposals with votes), the share of voting power held by the largest wallets is:
* **Median top-4 wallets: 53.7%** of voting power; **median top-10 wallets: 86.8%**.
* **Optimism mass elections** (12,000–64,000 voters each) sit at **45–55%** for the top 4 — e.g. Badgeholder Nomination 54.5%, Velodrome 46.8%, Cycle #9a Grants Council 47.7%.
* **Small, delegate-driven Uniswap votes are the most concentrated**: top-4 wallets hold 99.7% (sentinel rotation, 383 voters) and 98.4% (governance statute RFC, 133 voters).

> **Correction:** earlier versions of this README reported 87–94% top-4 concentration and a ~82% median. Those figures came from a capped sample (the first 500–1,000 votes of each proposal, because Snapshot limits one request to 1,000), which overstated concentration on large votes. The numbers above use every vote.

---

## 3. System Architecture

For a file-by-file view of ingestion, storage, indexing, retrieval, and API
data movement, see [`DATA_FLOW.md`](./DATA_FLOW.md).

```mermaid
flowchart TD
    subgraph Ingestion ["1. Multi-Source Ingestion"]
        SNAP["Snapshot GraphQL API<br/>(Proposals, Choices, Votes, Scores)"]
        DISC["Discourse Forum Scraper<br/>(Threads, Posts, Delegates, Dissent)"]
    end

    subgraph Storage ["2. Dual-Layer Storage"]
        SQL[("SQLite Relational DB<br/>dao_intelligence.db<br/>(proposals, votes, forum_posts)")]
        RESOLV["Entity Resolution Engine<br/>(Regex + Levenshtein Matching<br/>Wallet &harr; Forum Username)"]
        CHROMA[("ChromaDB Vector Store<br/>(BAAI/bge-small-en-v1.5<br/>2,988 Embedded Chunks)")]
    end

    subgraph Engine ["3. Intelligent Agent & Retrieval"]
        FILTER["Scoping Filter<br/>(By proposal_id / distance &le; 0.70)"]
        PROMPT["Context Assembly<br/>(Structured System + Source Citations)"]
        LLM["Tiered Resilient LLM Router<br/>Groq (Primary) &rarr; Gemini &rarr; OpenRouter &rarr; Mistral"]
    end

    subgraph API ["4. Production Serving Layer"]
        FAST["FastAPI Service<br/>(Interactive OpenAPI Swagger)"]
        C1["GET /daos"]
        C2["GET /proposals/{id}/concentration"]
        C3["POST /chat"]
    end

    SNAP --> SQL
    DISC --> SQL
    SQL --> RESOLV --> CHROMA
    SQL --> CHROMA
    CHROMA --> FILTER --> PROMPT --> LLM
    SQL --> FAST
    LLM --> FAST
    FAST --> C1
    FAST --> C2
    FAST --> C3
```

---

## 4. Quantitative Evaluation (RAG Triad)

To validate the retrieval and generation pipeline, an automated evaluation harness (`eval/eval_harness.py`) was run against a golden ground-truth benchmark (`eval/golden_dataset.py`) evaluated via an LLM judge:

| Metric | Score | Industry Benchmark | What It Proves |
|:---|:---:|:---:|:---|
| **Answer Relevancy** | **1.00 (100%)** | > 0.85 | 100% of answers directly answered the user's governance question without drift. |
| **Faithfulness** | **0.90 (90%)** | > 0.80 | 90% of claims made in generated responses were strictly supported by cited source chunks. |
| **Context Recall** | **0.87 (87%)** | > 0.75 | 87% of ground-truth reference chunks were successfully surfaced in the top-5 vector search. |
| **Context Precision** | **0.21** | — | Top-5 retrieval scoping keeps prompt token count within free-tier limits while capturing ground-truth. |

---

## 5. API Reference & Live Endpoints

The API is served with FastAPI at `http://127.0.0.1:8000`. Interactive documentation is available at **`/docs`**.

### Endpoints Overview

| Method | Endpoint | Query / Body Params | Description |
|:---|:---|:---|:---|
| `GET` | `/` | None | Service health status and registered route overview. |
| `GET` | `/daos` | None | Summary of all 5 DAOs with silence ratio, forum coverage, and proposal counts. |
| `GET` | `/daos/{space_id}` | `space_id` (path) | Detail for a single DAO including its top proposals by participation. |
| `GET` | `/proposals` | `space_id`, `min_votes`, `limit`, `offset` | Filterable proposal list with voting metadata and discussion links. |
| `GET` | `/proposals/{id}` | `proposal_id` (path) | Proposal detail, body text, choices, total votes, and forum thread. |
| `GET` | `/proposals/{id}/concentration` | `top_n=4` (query) | Computes whale voter dominance (Top-N share % and voter wallet breakdown). |
| `POST` | `/chat` | `{"query": str, "proposal_id": opt, "n_results": 5}` | Natural-language Q&A with source chunk citations and fallback provider info. |

### Sample `POST /chat` Payload & Response

**Request:**
```bash
curl -X POST "http://127.0.0.1:8000/chat" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "Why did delegates vote to ban Good Entry in the Watchdog Program?",
       "proposal_id": "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c"
     }'
```

**Response:**
```json
{
  "query": "Why did delegates vote to ban Good Entry in the Watchdog Program?",
  "proposal_id": "0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c",
  "provider": "groq",
  "chunks_found": 5,
  "answer": "Delegates voted to permanently ban Good Entry based on the findings from the Watchdog Program regarding high-severity misuse of grant funds [Source 1, Source 2]. Furthermore, delegates noted that Good Entry failed to respond or communicate in the public forum during the official response window [Source 4, Source 5].",
  "sources": [
    {
      "id": "proposal_0x472fb3b40d3df9b1a65de03b85e4867a76f7b1ec014e2d69f347256b0d08184c_0",
      "source_type": "proposal_body",
      "distance": 0.384,
      "author": null
    },
    {
      "id": "forum_post_78189",
      "source_type": "forum_post",
      "distance": 0.412,
      "author": "Zeptimus"
    }
  ]
}
```

---

## 6. Engineering Decisions & Architecture Trade-offs

1. **Why SQLite for Relational Ingestion instead of Postgres?**
   * *Rationale:* The ingestion pipeline is write-infrequent (batch Snapshot & Discourse sync) and read-heavy. SQLite provides sub-millisecond local reads with zero infrastructure overhead. It currently runs in its default rollback-journal mode; enabling WAL (Write-Ahead Logging) would let API reads continue while a sync is writing. Per-request connections with clean context teardown prevent connection leaks while keeping the data layer trivial to migrate to PostgreSQL.
2. **Why Local ChromaDB PersistentClient?**
   * *Rationale:* Avoids distributed network hops for vector search. Using `BAAI/bge-small-en-v1.5` embeddings (384 dimensions) provides high semantic density and fast Euclidean/cosine distance calculations while fitting comfortably in memory.
3. **Why a Multi-Tier Resilient LLM Router?**
   * *Rationale:* Free-tier inference providers enforce strict TPM (Tokens Per Minute) and RPM limits (e.g. Groq 8,000 TPM on large models). The engine implements a tiered fallback:
     $$\text{Groq (Ultra-Low Latency)} \xrightarrow{429 / \text{Error}} \text{Google Gemini} \xrightarrow{\text{Fail}} \text{OpenRouter} \xrightarrow{\text{Fail}} \text{Mistral}$$
   * Ensures uninterrupted service even during peak rate-limiting events.
4. **Distance Filtering (`max_distance = 0.70`):**
   * *Rationale:* Standard vector search returns the top $K$ items regardless of quality. Enforcing a cosine distance ceiling prevents irrelevant chunks from diluting prompt context and causing hallucinated answers.

---

## 7. Quickstart & Installation

### Prerequisites
* Python 3.11+
* Git

### Setup
```bash
# Clone repository
git clone https://github.com/Rakshitgoyal770/DOA-BACKEND.git
cd DOA-BACKEND

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate       # Windows
# source .venv/bin/activate    # Linux / macOS

# Install dependencies
pip install -r requirements.txt
```

### Environment Configuration (`.env`)
```ini
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
OPENROUTER_API_KEY=your_openrouter_key
MISTRAL_API_KEY=your_mistral_key
```

### Running the API
```bash
uvicorn main:app --port 8000 --reload
```
Navigate to `http://127.0.0.1:8000/docs` to test endpoints via Swagger.

### Keeping the Data Fresh
Run these in order after new governance activity (each step only processes what changed):
```bash
python -m features.sync.runner --sync-all     # proposals, forum posts, every missing vote
python -m features.identity.runner --upgrade  # re-check wallet links (offline)
python -m vector.embedding                    # embed only new/changed documents
python -m features.sync.runner --check        # audit, including vote completeness
```

### Running the Tests
```bash
python -m pytest
```
Offline unit tests use a temporary database and fakes; `tests/test_regression_real_db.py`
pins verified values from the real database and is skipped when it is absent.

### Running the Evaluation Harness
```bash
python -m eval.eval_harness
```

---

## 8. SDE Resume Bullet Points

You can copy and adapt these bullet points directly for software engineering and backend roles:

* **Backend / Distributed Systems:**
  > *“Engineered a production-ready governance intelligence backend using FastAPI, SQLite, and ChromaDB, ingesting 117 proposals and 515,000+ votes across 5 DAOs from Snapshot GraphQL and Discourse APIs.”*

* **Machine Learning / RAG:**
  > *“Architected an evaluated RAG pipeline with dense vector indexing (BAAI/bge-small-en-v1.5) and a 4-tier resilient LLM fallback router (Groq &rarr; Gemini &rarr; OpenRouter &rarr; Mistral) with automatic 429 backoff handling.”*

* **Evaluation & Impact:**
  > *“Benchmarked retrieval quality using an automated LLM-as-a-judge evaluation harness over a golden dataset, achieving 87% Context Recall, 90% Faithfulness, and 100% Answer Relevancy.”*

* **Data Engineering & Analytics:**
  > *“Conducted whale concentration and voter silence analysis on Snapshot governance, measuring that the median top-4 wallets control ~54% of voting power (top-10: ~87%) while <1% of voting wallets participate in forum deliberation.”*
