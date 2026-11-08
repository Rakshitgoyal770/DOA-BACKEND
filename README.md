# Quorum monorepo

- `frontend/`: the Quorum UI. See [frontend/README.md](frontend/README.md) for how to run it and which backend endpoints it uses.
- `Backend Doa/`: a copy of the DAO Governance Intelligence API (reference only; the live backend is the separate `Backend Doa` project).

```bash
npm install
npm run dev      # frontend on http://localhost:5173 (needs the API on :8000)
npm run build
npm test
npm run lint
```
