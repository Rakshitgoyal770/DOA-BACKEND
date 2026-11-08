import type { ProposalState } from '../api/types';

/**
 * What a proposal's status is *right now*.
 *
 * The backend reports `state` as of its last sync (GET /sync/status shows when). A
 * proposal synced as "active" whose voting window has since ended would otherwise be
 * shown as live, inviting a vote that can no longer be cast. So for anything not already
 * closed we also look at the proposal's start/end timestamps.
 */
export type DisplayStatus = 'active' | 'pending' | 'closed' | 'ended';

export function deriveStatus(
  p: { state: ProposalState | string | null; start_ts: number | null; end_ts: number | null },
  nowUnix: number = Date.now() / 1000,
): DisplayStatus {
  if (p.state === 'closed') return 'closed';
  if (p.end_ts && nowUnix > p.end_ts) return 'ended';
  if (p.start_ts && nowUnix < p.start_ts) return 'pending';
  if (p.state === 'active' || p.state === 'pending') return 'active';
  return p.state === null && p.end_ts ? 'active' : 'closed';
}

export const STATUS_LABEL: Record<DisplayStatus, string> = {
  active: 'Active',
  pending: 'Upcoming',
  closed: 'Closed',
  ended: 'Ended',
};

export const STATUS_HINT: Partial<Record<DisplayStatus, string>> = {
  ended:
    'Voting has ended, but the stored data was last synced while it was still open, so the tallies shown may not be final.',
};

/** Voting is open: the only status for which "vote on Snapshot" makes sense. */
export const isVotable = (s: DisplayStatus) => s === 'active';
