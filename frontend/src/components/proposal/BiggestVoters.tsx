import React from 'react';
import { CheckCircle2, CircleDashed } from 'lucide-react';
import type { ProposalParticipants, VoteRow } from '../../api/types';
import { computeCoverageGap } from '../../lib/analytics';
import { formatPct, truncateAddress } from '../../lib/format';
import { Link } from '../ui/Link';
import { VoteChip } from './VoteChip';

/**
 * "Did the biggest voters speak?" The largest wallets on the proposal, how they voted, and
 * whether a forum post in its thread could be tied to them (the first page of GET /votes +
 * the participants list). A missing link is a lower bound, not proof of silence.
 */
export const BiggestVoters: React.FC<{ votes: VoteRow[]; participants: ProposalParticipants; onShowDiscussion: () => void }> = ({
  votes,
  participants,
  onShowDiscussion,
}) => {
  const gap = computeCoverageGap(votes, participants);
  const share = votes.reduce((sum, v) => sum + (v.power_share_pct ?? 0), 0);
  return (
    <div className="space-y-3">
      <p className="text-sm text-[#4A463F]">
        The top {gap.rows.length} wallets hold <strong>{formatPct(share)}</strong> of the voting power.{' '}
        {gap.withForumPost > 0 ? (
          <>
            <strong>{gap.withForumPost}</strong> of them posted in the discussion.
          </>
        ) : (
          'None of them posted in the discussion under a name we could link.'
        )}
      </p>
      <ol className="divide-y divide-[#F0ECE3]">
        {gap.rows.map(({ voter, poster }, i) => (
          <li key={voter.voter} className="py-2 flex items-start gap-2.5 text-sm">
            {poster ? (
              <CheckCircle2 size={15} className="text-[#23593F] mt-0.5 shrink-0" aria-label="Posted in the discussion" />
            ) : (
              <CircleDashed size={15} className="text-[#BDB3A1] mt-0.5 shrink-0" aria-label="No linked forum post" />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className={`truncate text-xs ${voter.ens_name ? 'font-medium' : 'font-mono'}`} title={voter.voter}>
                  {i + 1}. {voter.ens_name ?? poster?.ens_name ?? truncateAddress(voter.voter, 4)}
                </span>
                <span className="font-mono text-[11px] text-[#5C5852] shrink-0">{formatPct(voter.power_share_pct)}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <VoteChip choice={voter.choice} />
                {poster && (
                  <Link to={`/person/${encodeURIComponent(poster.username)}`} className="text-xs text-[#164054] hover:underline">
                    @{poster.username} · {poster.posts} post{poster.posts === 1 ? '' : 's'}
                  </Link>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
      <button type="button" onClick={onShowDiscussion} className="text-xs font-medium underline underline-offset-2 cursor-pointer">
        Read what they said
      </button>
    </div>
  );
};
