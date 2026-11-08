/**
 * The proposal catalogue: every proposal the backend holds, fetched once and
 * cached.
 *
 * WHY THIS EXISTS
 *   GET /proposals has no text search, no total count and one fixed order (most
 *   voted first), and caps a page at 100. The explorer, global search and the
 *   Insights page all need to filter / sort across everything, so we page through
 *   the endpoint until a short page comes back and filter locally.
 *   (The dataset is ~120 proposals, so this is 2 requests. If it ever grows to
 *   thousands, the backend needs server-side search; see the README gap list.)
 */
import { api } from './endpoints';
import type { ProposalSummary } from './types';

const PAGE_SIZE = 100;
const MAX_PAGES = 50; // safety stop: 5,000 proposals
const TTL_MS = 60_000;

let cache: { at: number; data: ProposalSummary[] } | null = null;
let inflight: Promise<ProposalSummary[]> | null = null;

async function fetchAll(): Promise<ProposalSummary[]> {
  const all: ProposalSummary[] = [];
  for (let page = 0; page < MAX_PAGES; page++) {
    const rows = await api.listProposals({ limit: PAGE_SIZE, skip: page * PAGE_SIZE });
    all.push(...rows);
    if (rows.length < PAGE_SIZE) break;
  }
  return all;
}

/** All proposals. Concurrent callers share one request; results are cached for a minute. */
export function getProposalCatalogue(force = false): Promise<ProposalSummary[]> {
  if (!force && cache && Date.now() - cache.at < TTL_MS) return Promise.resolve(cache.data);
  if (inflight) return inflight;
  inflight = fetchAll()
    .then((data) => {
      cache = { at: Date.now(), data };
      return data;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/** Test hook. */
export function clearCatalogueCache(): void {
  cache = null;
  inflight = null;
}
