import type { ProposalParticipant, ProposalParticipants, VoterEntry } from '../api/types';

/**
 * "Coverage gap": for the largest voters on a proposal, did any of them have a forum
 * post in that proposal's discussion thread that we could tie to their wallet?
 *
 * Built purely from two real endpoints:
 *   GET /proposals/{id}/concentration   -> who the top voters are
 *   GET /identities/proposal/{id}       -> forum posters, with wallets where a link exists
 *
 * Reading the result honestly: "no linked forum post" does NOT mean the voter said
 * nothing publicly. Only a minority of forum users are linked to wallets (see
 * GET /identities/stats), so this is a lower bound on public engagement.
 */
export interface CoverageRow<V extends { voter: string } = VoterEntry> {
  voter: V;
  /** the forum poster whose linked wallet is this voter, if any */
  poster: ProposalParticipant | null;
}

export interface CoverageGap<V extends { voter: string } = VoterEntry> {
  rows: CoverageRow<V>[];
  /** top voters with a linked forum post on this proposal */
  withForumPost: number;
  /** top voters with none */
  withoutForumPost: number;
}

const norm = (s: string | null | undefined) => (s ?? '').toLowerCase();

export function computeCoverageGap<V extends { voter: string }>(
  voters: V[],
  participants: ProposalParticipants,
): CoverageGap<V> {
  const byWallet = new Map<string, ProposalParticipant>();
  for (const p of participants.participants) {
    if (p.wallet_address) byWallet.set(norm(p.wallet_address), p);
  }
  const rows = voters.map<CoverageRow<V>>((voter) => ({
    voter,
    poster: byWallet.get(norm(voter.voter)) ?? null,
  }));
  const withForumPost = rows.filter((r) => r.poster).length;
  return { rows, withForumPost, withoutForumPost: rows.length - withForumPost };
}

/** Index of the winning choice, or -1 when there are no scores. */
export function leadingChoiceIndex(scores: number[]): number {
  if (!scores.length) return -1;
  let best = 0;
  for (let i = 1; i < scores.length; i++) if (scores[i] > scores[best]) best = i;
  return scores[best] > 0 ? best : -1;
}
