# Quorum frontend

Read-only governance analytics UI for the **DAO Governance Intelligence API** (the FastAPI backend in `Backend Doa`).
React 19 · TypeScript (strict) · Vite 8 · Tailwind 4. No mock data: every number comes from the API.

## Run it

```bash
# 1. backend (separate repo / folder), from its root, with its venv active
uvicorn main:app --port 8000

# 2. frontend, from the monorepo root ("Doa voting")
npm install
npm run dev            # http://localhost:5173
```

The API address is `VITE_API_BASE_URL` (default `http://127.0.0.1:8000`); copy `.env.example` to `.env.local` to change it.
The backend allows any origin (CORS `*`), so no proxy is needed.

| Command | What it does |
|---|---|
| `npm run dev` | dev server |
| `npm run build` | `tsc -b` (strict) + production build into `frontend/dist` |
| `npm run lint` | oxlint |
| `npm test` | 69 unit tests (client, formatting, status, answer parser, filters, coverage gap, catalogue paging, freshness, result note, proposal-text rendering) |
| `VITE_INTEGRATION=1 npm run test:integration` | 16 contract tests against a **running** backend (add `VITE_INTEGRATION_CHAT=1` to also call `POST /chat`, which uses LLM quota) |

## What the backend supports (and so what the UI does)

The backend is a **read-only analytics + RAG service**. It has no authentication, users, roles, vote submission or notifications, so the UI has none either.

| Screen | Route | Endpoints |
|---|---|---|
| Proposals (landing) | `#/?q&dao&status&sort&page` (`#/proposals` too) | proposal catalogue (`GET /proposals`, paged), `GET /daos`, `GET /sync/status` |
| Proposal (the core) | `#/proposal/:id?tab=text\|votes\|discussion` | `GET /proposals/{id}` (full `body`), `GET /proposals/{id}/votes` (paged, sorted, searched, by choice), `GET /proposals/{id}/posts` (full posts with author wallet + vote), `GET /identities/proposal/{id}` |
| DAOs | `#/daos`, `#/dao/:spaceId` | `GET /daos`, `GET /daos/{id}`, proposal catalogue |
| People | `#/people`, `#/person/:username` (old `#/identities…` links still work) | `GET /identities`, `/identities/stats`, `/identities/{username}`, `GET /proposals/{id}/posts` (their posts, loaded per vote) |
| Footer: how it works, data coverage, cross-DAO research | `#/methodology`, `#/data`, `#/insights` | `GET /sync/status`, `GET /daos`, proposal catalogue |
| Analyst drawer | (global; 3 levels, see below) | `POST /chat` |
| Search (Ctrl+K) | (global) | proposal catalogue (local), `GET /identities?q=` |

### Analyst levels

The drawer asks at the most specific level the current page offers, and the user can switch:

| Level | Offered on | How it is scoped |
|---|---|---|
| This proposal | proposal page | backend `proposal_id` |
| A DAO | DAO page, proposal page | **no backend parameter exists**; the question is sent as `About <DAO name> only: <question>` and the agent passes `dao=` to its lookups (verified: `list_proposals dao=arbitrum`) |
| All DAOs | everywhere | no scope |

The DAO level is a prompt-level workaround, so it is a strong hint to the agent, not a hard filter. Each turn in the history is tagged with the level it was asked at.

To vote, active proposals link out to Snapshot; this app never handles keys or wallets.

Deliberately **not** wired: `POST /sync/run`, `POST /identities/resolve`, `GET /identities/resolve/status`. They are unauthenticated, long-running, third-party-API-hitting jobs; exposing them in a public UI would let any visitor start them.

## Layout

```
src/api/        client (timeouts, FastAPI error parsing), typed endpoints, DTO types, proposal catalogue cache
src/hooks/      useAsync (cancellable fetch), hash router, debounce
src/lib/        pure logic: status, formatting, filters, coverage gap, analyst-answer parser
src/context/    DAO list, analyst drawer
src/components/ ui/ (primitives) · layout/ · proposal/ · analyst/ · search/
src/pages/      one file per route
```

## Backend limitations the UI works around

1. **No auth / voting / users / notifications**: features removed, not faked.
2. **`state` is a snapshot at last sync.** Proposals still "active" in the DB but past their end time are shown as **Ended** with a "tallies may not be final" note, and get no vote button (`lib/status.ts`).
3. **`GET /proposals` has no search, no total count, one fixed sort, max 100 per page.** The UI pages through it into a cached catalogue and filters/sorts locally (`api/catalogue.ts`). Fine for ~120 proposals; needs server-side search beyond a few thousand.
4. **`GET /daos/{id}` top proposals carry no timestamps**, so their status is enriched from the catalogue.
5. **`GET /sync/status` takes ~2 s** (it audits the DB); it is fetched once and shared (`api/freshness.ts`). "Last synced" is the newest fetch time: the backend records when rows change, not when a sync checked a DAO, so the oldest time would understate freshness.
6. **Voting power has no unit** in the API, so none is shown.
7. **Ballots are polymorphic** (`"For"`, `["A","B"]`, `{"A": 5, "B": 10}`); shown as cast, not forced into For/Against/Abstain.
8. **Identity coverage is low (~17% of forum users)**, so a post without a vote, or a big voter without a linked post, is labelled as "no wallet link" / a lower bound, not proof of silence.
9. **Proposal text is markdown from Snapshot.** Pictures are `ipfs://` addresses, read through Snapshot's own gateway (`lib/markdown.ts`; a browser cannot open `ipfs://`). Forum `upload://` pictures were never published, so they show as "Image not available"; 16 such references exist in 6 proposals. Scripts, `javascript:` and `data:` links are dropped.
10. **A backend older than this site** (no `body`, no `/votes`, no `/posts`) is detected and says so on the page, instead of showing the 500-character preview as if it were the proposal.
11. **No posts-by-person endpoint**: a person page loads their posts per voted proposal, on demand, from `GET /proposals/{id}/posts`.
9. **`/chat` citations**: Groq returns full-width `【Source 1】` brackets; the parser accepts both bracket styles. `[Source N]` maps to `sources[N-1]`.
10. **`/chat` can 500** when every LLM provider fails or is rate-limited; the drawer shows a plain-language message with Retry, and a 2-minute client timeout.
11. **`/chat` has no DAO parameter**: see Analyst levels above.
12. **Optimism's stored proposals date from Nov 2022 to Jan 2023** (it left Snapshot); noted on the Methodology page.
