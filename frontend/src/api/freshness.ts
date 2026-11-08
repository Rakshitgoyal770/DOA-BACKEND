/**
 * How fresh the stored data is: GET /sync/status, fetched once and shared.
 *
 * WHY THIS EXISTS
 *   /sync/status audits the whole database and takes a couple of seconds. The home page,
 *   the data page and the analyst all need it, so concurrent callers share one request
 *   and the result is reused for a minute (the data page's Refresh forces a new one).
 *
 * WHICH TIME WE SHOW
 *   The backend records when rows CHANGED, not when a sync last CHECKED: a DAO with no new
 *   proposals keeps its old fetch time even though the sync just looked at it. So the
 *   oldest fetch time understates freshness (it said "Oct 22" right after a Nov 7 sync).
 *   The newest fetch time across votes, forum posts and DAOs is the last time a sync wrote
 *   anything, the closest honest answer to "when was this last synced". The backend keeps no
 *   record of each sync run; storing one would let this say exactly when every DAO was checked.
 */
import { api } from './endpoints';
import type { SyncStatus } from './types';

const TTL_MS = 60_000;

let cache: { at: number; data: SyncStatus } | null = null;
let inflight: Promise<SyncStatus> | null = null;

export function getSyncStatus(force = false): Promise<SyncStatus> {
  if (!force && cache && Date.now() - cache.at < TTL_MS) return Promise.resolve(cache.data);
  if (inflight && !force) return inflight;
  const request: Promise<SyncStatus> = api
    .syncStatus()
    .then((data) => {
      cache = { at: Date.now(), data };
      return data;
    })
    .finally(() => {
      if (inflight === request) inflight = null; // a newer forced request may have replaced it
    });
  inflight = request;
  return request;
}

/** The newest fetch time across votes, forum posts and every DAO's proposals (ISO), or undefined. */
export function lastSyncActivity(s: SyncStatus | null | undefined): string | undefined {
  if (!s) return undefined;
  const times = [s.votes.last_fetched, s.forum.last_fetched, ...s.daos.map((d) => d.last_fetched)].filter(
    (t): t is string => !!t && !Number.isNaN(new Date(t).getTime()),
  );
  return times.sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0];
}

/** Test hook; also called when the backend comes back after an outage. */
export function clearSyncStatusCache(): void {
  cache = null;
  inflight = null;
}
