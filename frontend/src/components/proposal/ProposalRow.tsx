import React from 'react';
import { ChevronRight } from 'lucide-react';
import type { ProposalSummary } from '../../api/types';
import { daoMeta } from '../../lib/daoMeta';
import { formatDate, formatInt, formatPct, formatTimeRemaining } from '../../lib/format';
import { deriveStatus } from '../../lib/status';
import { StatusBadge } from '../ui/Badge';
import { Link } from '../ui/Link';

interface ProposalRowProps {
  proposal: ProposalSummary;
  daoName: string;
  showDao?: boolean;
}

/** One proposal in a list: where, when, what, and how much voting and talking it drew. */
export const ProposalRow: React.FC<ProposalRowProps> = ({ proposal: p, daoName, showDao = true }) => {
  const status = deriveStatus(p);
  const meta = daoMeta(p.space_id, daoName);
  const when =
    status === 'active' ? formatTimeRemaining(p.end_ts) : status === 'pending' ? `Starts ${formatDate(p.start_ts)}` : `Ended ${formatDate(p.end_ts)}`;
  return (
    <Link
      to={`/proposal/${encodeURIComponent(p.id)}`}
      className="group block p-4 sm:p-5 bg-white border border-[#E8E2D8] rounded-xl hover:border-[#181715] hover:shadow-subtle transition-all"
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {showDao && (
              <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-[#4A463F]">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: meta.color }} aria-hidden />
                {daoName}
              </span>
            )}
            <StatusBadge status={status} />
            <span className="text-[11px] text-[#7D776E]">{when}</span>
          </div>
          <h3 className="font-serif text-lg sm:text-xl leading-snug text-[#181715] group-hover:underline decoration-[#BDB3A1] underline-offset-2 break-words">
            {p.title}
          </h3>
          <dl className="flex flex-wrap gap-x-6 gap-y-1 pt-0.5 text-xs text-[#5C5852]">
            <div className="flex gap-1">
              <dt className="sr-only">Voters</dt>
              <dd>
                <strong className="font-mono text-[#181715]">{formatInt(p.votes_count)}</strong> voters
              </dd>
            </div>
            <div className="flex gap-1">
              <dt className="sr-only">People in the discussion</dt>
              <dd>
                <strong className="font-mono text-[#181715]">{formatInt(p.forum_posters)}</strong> {p.forum_posters === 1 ? 'person' : 'people'} discussed it
              </dd>
            </div>
            {p.top_choice_share_pct !== null && (
              <div className="flex gap-1" title="Share of all voting power behind the leading option.">
                <dt className="sr-only">Leading option</dt>
                <dd>
                  leading option <strong className="font-mono text-[#181715]">{formatPct(p.top_choice_share_pct)}</strong>
                </dd>
              </div>
            )}
          </dl>
        </div>
        <ChevronRight size={18} className="text-[#BDB3A1] group-hover:text-[#181715] mt-1 shrink-0" aria-hidden />
      </div>
    </Link>
  );
};
