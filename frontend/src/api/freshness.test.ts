import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { SyncStatus } from './types';
import { clearSyncStatusCache, getSyncStatus, lastSyncActivity } from './freshness';
import { ResultByChoice } from '../components/proposal/ResultByChoice';
import { methodLabel } from '../lib/format';

const status = (votes: string, forum: string, daos: string[]) =>
  ({ votes: { last_fetched: votes }, forum: { last_fetched: forum }, daos: daos.map((t) => ({ last_fetched: t })) }) as unknown as SyncStatus;

beforeEach(() => clearSyncStatusCache());
afterEach(() => vi.unstubAllGlobals());

describe('lastSyncActivity', () => {
  it('is the NEWEST fetch time: a DAO with nothing new keeps its old time after a sync checked it', () => {
    // real values from GET /sync/status after the 2026-11-07 sync: Optimism and Uniswap had nothing
    // new, so their rows still say Oct 22; the oldest time would claim nothing was synced since then.
    const s = status('2026-11-07T13:05:25', '2026-11-07T12:57:20', ['2026-11-07T12:57:02', '2026-10-22T08:47:52']);
    expect(lastSyncActivity(s)).toBe('2026-11-07T13:05:25');
  });
  it('skips missing or unparseable times and handles no status', () => {
    expect(lastSyncActivity(status('', 'not a date', ['2026-10-01T00:00:00']))).toBe('2026-10-01T00:00:00');
    expect(lastSyncActivity(null)).toBeUndefined();
  });
});

describe('getSyncStatus', () => {
  it('shares one request between callers and reuses it until forced', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ total_proposals: 1 }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await Promise.all([getSyncStatus(), getSyncStatus()]);
    await getSyncStatus();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await getSyncStatus(true); // the data page's Refresh
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe('ResultByChoice', () => {
  const html = (scores: number[], total: number) =>
    renderToStaticMarkup(createElement(ResultByChoice, { choices: scores.map((_, i) => `C${i}`), scores, scoresTotal: total, open: false }));

  it('explains approval votes, whose choice shares add up to more than 100%', () => {
    // 'Special Voting Cycle #9b' style: every voter backs several candidates (sum = 4.3x the total)
    expect(html([300, 250, 200, 180], 216)).toContain('add up to more than 100%');
  });
  it('says nothing extra for an ordinary single-choice vote', () => {
    expect(html([900, 100], 1000)).not.toContain('more than 100%');
  });
});

describe('methodLabel', () => {
  it('names known linking methods and falls back to readable text', () => {
    expect(methodLabel('profile_wallet')).toBe('Wallet in forum profile');
    expect(methodLabel('some_new_method')).toBe('some new method');
  });
});
