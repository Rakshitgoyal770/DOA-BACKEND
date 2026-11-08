import type { ProposalSummary } from '../api/types';
import { deriveStatus, type DisplayStatus } from './status';

export type SortKey = 'newest' | 'votes' | 'discussed' | 'contested' | 'oldest';

export interface ExplorerFilters {
  q: string;
  dao: string;
  status: DisplayStatus | 'all';
  sort: SortKey;
  page: number;
}

/** Newest first: someone following governance wants what is new before what was big. */
export const DEFAULT_FILTERS: ExplorerFilters = { q: '', dao: '', status: 'all', sort: 'newest', page: 0 };

export const SORTS: { key: SortKey; label: string }[] = [
  { key: 'newest', label: 'Newest first' },
  { key: 'votes', label: 'Most voters' },
  { key: 'discussed', label: 'Most discussed' },
  { key: 'contested', label: 'Most contested' },
  { key: 'oldest', label: 'Oldest first' },
];

const num = (v: number | null | undefined, fallback: number) => (v === null || v === undefined ? fallback : v);

const COMPARATORS: Record<SortKey, (a: ProposalSummary, b: ProposalSummary) => number> = {
  newest: (a, b) => num(b.start_ts, 0) - num(a.start_ts, 0),
  votes: (a, b) => num(b.votes_count, -1) - num(a.votes_count, -1),
  discussed: (a, b) => b.forum_posters - a.forum_posters,
  // closest result first: the smallest leading share; proposals without a result sort last
  contested: (a, b) => {
    const x = num(a.top_choice_share_pct, Infinity);
    const y = num(b.top_choice_share_pct, Infinity);
    return x === y ? 0 : x < y ? -1 : 1; // not x - y: Infinity - Infinity is NaN
  },
  oldest: (a, b) => num(a.start_ts, 0) - num(b.start_ts, 0),
};

/** Apply search, DAO, status and sort to the catalogue. Returns a new array. */
export function filterProposals(
  proposals: ProposalSummary[],
  f: Pick<ExplorerFilters, 'q' | 'dao' | 'status' | 'sort'>,
  now = Date.now() / 1000,
): ProposalSummary[] {
  const q = f.q.trim().toLowerCase();
  return proposals
    .filter((p) => !f.dao || p.space_id === f.dao)
    .filter((p) => f.status === 'all' || deriveStatus(p, now) === f.status)
    .filter((p) => !q || p.title.toLowerCase().includes(q) || p.id.toLowerCase().startsWith(q))
    .sort(COMPARATORS[f.sort]);
}

/** How many proposals of the list have each display status (for the status tabs). */
export function countByStatus(proposals: ProposalSummary[], now = Date.now() / 1000): Record<DisplayStatus, number> {
  const counts: Record<DisplayStatus, number> = { active: 0, pending: 0, ended: 0, closed: 0 };
  for (const p of proposals) counts[deriveStatus(p, now)] += 1;
  return counts;
}

export function parseFilters(query: URLSearchParams): ExplorerFilters {
  const status = query.get('status');
  const sort = query.get('sort');
  const page = Number(query.get('page'));
  return {
    q: query.get('q') ?? '',
    dao: query.get('dao') ?? '',
    status: (['active', 'pending', 'ended', 'closed'] as const).find((s) => s === status) ?? 'all',
    sort: SORTS.find((s) => s.key === sort)?.key ?? DEFAULT_FILTERS.sort,
    page: Number.isInteger(page) && page > 0 ? page : 0,
  };
}

/** Only non-default values go into the URL, so the common case stays `#/`. */
export function filtersToParams(f: ExplorerFilters): Record<string, string | number | null> {
  return {
    q: f.q || null,
    dao: f.dao || null,
    status: f.status === 'all' ? null : f.status,
    sort: f.sort === DEFAULT_FILTERS.sort ? null : f.sort,
    page: f.page > 0 ? f.page : null,
  };
}
