import React, { useState } from 'react';
import { ExternalLink as ExternalIcon, Search } from 'lucide-react';
import { api } from '../../api/endpoints';
import type { VoteSort } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { useDebounced } from '../../hooks/useDebounced';
import { formatCompact, formatDate, formatInt, formatPct, truncateAddress } from '../../lib/format';
import { ConfidenceBadge } from '../ui/Badge';
import { Select, TextInput } from '../ui/Field';
import { ExternalLink, Link } from '../ui/Link';
import { Meter } from '../ui/Meter';
import { Pagination } from '../ui/Pagination';
import { EmptyState, ErrorState, LoadingBlock } from '../ui/States';
import { VoteChip } from './VoteChip';

const PAGE_SIZE = 50;

const SORT_LABEL: Record<VoteSort, string> = {
  voting_power: 'Most voting power',
  voting_power_asc: 'Least voting power',
  newest: 'Most recent',
  oldest: 'Earliest',
};

/**
 * Every vote of a proposal (GET /proposals/{id}/votes). Paging, sorting, search and the
 * choice filter all run on the server, so this works the same for 10 votes or 60,000.
 */
export const VotesTable: React.FC<{ proposalId: string; choices: string[] }> = ({ proposalId, choices }) => {
  const [draft, setDraft] = useState('');
  const q = useDebounced(draft.trim(), 300);
  const [sort, setSort] = useState<VoteSort>('voting_power');
  const [choice, setChoice] = useState<number | null>(null);
  const [withReason, setWithReason] = useState(false);
  // the page belongs to one filter combination; changing a filter starts again at page 1
  const key = `${q}|${sort}|${choice}|${withReason}`;
  const [paging, setPaging] = useState({ key, page: 0 });
  const page = paging.key === key ? paging.page : 0;

  const state = useAsync(
    (signal) =>
      api.proposalVotes(
        proposalId,
        { limit: PAGE_SIZE, offset: page * PAGE_SIZE, sort, q: q || undefined, choice: choice ?? undefined, with_reason: withReason || undefined },
        { signal },
      ),
    [proposalId, page, sort, q, choice, withReason],
    { keepPrevious: true },
  );
  const data = state.data;
  const filtered = !!q || choice !== null || withReason;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="relative flex-1 min-w-[220px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8C867D] pointer-events-none" aria-hidden />
          <TextInput
            type="search"
            aria-label="Search voters"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Search wallet, ENS name or forum user"
            maxLength={100}
            className="w-full pl-9"
          />
        </div>
        <Select aria-label="Sort votes" value={sort} onChange={(e) => setSort(e.target.value as VoteSort)}>
          {(Object.keys(SORT_LABEL) as VoteSort[]).map((s) => (
            <option key={s} value={s}>
              {SORT_LABEL[s]}
            </option>
          ))}
        </Select>
      </div>

      {choices.length > 0 && (
        <div role="group" aria-label="Filter by choice" className="flex flex-wrap gap-1.5">
          <ChoiceButton active={choice === null} onClick={() => setChoice(null)}>
            Every vote
          </ChoiceButton>
          {choices.map((c, i) => (
            <ChoiceButton key={`${i}-${c}`} active={choice === i + 1} onClick={() => setChoice(choice === i + 1 ? null : i + 1)}>
              {c}
            </ChoiceButton>
          ))}
        </div>
      )}
      <label className="inline-flex items-center gap-2 text-xs text-[#4A463F] cursor-pointer select-none">
        <input type="checkbox" checked={withReason} onChange={(e) => setWithReason(e.target.checked)} className="accent-[#181715]" />
        Only votes with a written reason
      </label>

      {state.error && !data ? (
        <ErrorState error={state.error} onRetry={state.reload} compact />
      ) : !data ? (
        <LoadingBlock label="Loading votes" rows={8} />
      ) : data.stored_votes === 0 ? (
        <EmptyState title="No individual votes stored yet" description="They appear after the next vote sync." />
      ) : (
        <>
          <p className="text-xs text-[#5C5852]" aria-live="polite">
            {filtered ? `${formatInt(data.matched)} of ${formatInt(data.stored_votes)} votes match` : `${formatInt(data.stored_votes)} votes`}
            {!data.complete && ` · we hold ${formatInt(data.stored_votes)} of the ${formatInt(data.expected_votes)} Snapshot reports; shares are measured against Snapshot's total`}
            {choice !== null && choices.length > 0 && ' · ballots that include this choice (one voter can back several on approval votes)'}
            {!data.reasons_complete && ' · written reasons are still being loaded for some older votes'}
          </p>

          {data.votes.length === 0 ? (
            <EmptyState title="No votes match" description="Try a shorter search or another choice." />
          ) : (
            <>
            <ol className={`sm:hidden divide-y divide-[#F0ECE3] transition-opacity ${state.loading ? 'opacity-60' : ''}`} aria-label="Votes on this proposal">
              {data.votes.map((v, i) => (
                <li key={v.voter} className="py-3 space-y-1.5">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0 truncate text-sm" title={v.voter}>
                      <span className="font-mono text-[11px] text-[#8C867D] mr-1.5">{data.offset + i + 1}</span>
                      <span className={v.ens_name ? 'font-medium' : 'font-mono text-xs'}>{v.ens_name ?? truncateAddress(v.voter, 5)}</span>
                    </span>
                    <span className="font-mono text-xs shrink-0">
                      {formatCompact(v.voting_power)} <span className="text-[#8C867D]">· {formatPct(v.power_share_pct)}</span>
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <VoteChip choice={v.choice} className="max-w-[70%]" />
                    {v.forum_users.map((u) => (
                      <Link key={u.username} to={`/person/${encodeURIComponent(u.username)}`} className="text-xs text-[#164054] hover:underline">
                        @{u.username}
                      </Link>
                    ))}
                    <span className="text-[11px] text-[#8C867D] ml-auto">{formatDate(v.created_ts)}</span>
                  </div>
                  {v.reason && <Reason text={v.reason} />}
                </li>
              ))}
            </ol>
            <div className={`hidden sm:block overflow-x-auto -mx-1 px-1 transition-opacity ${state.loading ? 'opacity-60' : ''}`}>
              <table className="w-full text-sm min-w-[680px]">
                <caption className="sr-only">Votes on this proposal</caption>
                <thead>
                  <tr className="text-left border-b border-[#E8E2D8]">
                    <th scope="col" className="editorial-label text-[9px] py-2 pr-3 w-10">#</th>
                    <th scope="col" className="editorial-label text-[9px] py-2 pr-3">Voter</th>
                    <th scope="col" className="editorial-label text-[9px] py-2 pr-3">Vote</th>
                    <th scope="col" className="editorial-label text-[9px] py-2 pr-3 w-44">Voting power</th>
                    <th scope="col" className="editorial-label text-[9px] py-2">When</th>
                  </tr>
                </thead>
                <tbody>
                  {data.votes.map((v, i) => (
                    <tr key={v.voter} className="border-b border-[#F0ECE3] align-top">
                      <td className="py-2.5 pr-3 font-mono text-xs text-[#8C867D]">{data.offset + i + 1}</td>
                      <td className="py-2.5 pr-3 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className={v.ens_name ? 'font-medium' : 'font-mono text-xs'} title={v.voter}>
                            {v.ens_name ?? truncateAddress(v.voter, 5)}
                          </span>
                          <ExternalLink href={`https://snapshot.org/#/profile/${v.voter}`} aria-label="Voter's Snapshot profile" className="text-[#8C867D] hover:text-[#181715]">
                            <ExternalIcon size={11} aria-hidden />
                          </ExternalLink>
                        </div>
                        {v.forum_users.map((u) => (
                          <div key={u.username} className="flex items-center gap-1.5 mt-0.5 text-xs">
                            <Link to={`/person/${encodeURIComponent(u.username)}`} className="text-[#164054] hover:underline">
                              @{u.username}
                            </Link>
                            <ConfidenceBadge level={u.confidence_level} />
                          </div>
                        ))}
                      </td>
                      <td className="py-2.5 pr-3 max-w-[300px]">
                        <VoteChip choice={v.choice} />
                        {v.reason && <Reason text={v.reason} />}
                      </td>
                      <td className="py-2.5 pr-3">
                        <div className="font-mono text-xs">
                          {formatCompact(v.voting_power)} <span className="text-[#8C867D]">· {formatPct(v.power_share_pct)}</span>
                        </div>
                        <Meter value={v.power_share_pct ?? 0} className="mt-1" label={`${formatPct(v.power_share_pct)} of voting power`} />
                      </td>
                      <td className="py-2.5 text-xs text-[#5C5852] whitespace-nowrap">{formatDate(v.created_ts)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            </>
          )}
          {state.error && <ErrorState error={state.error} onRetry={state.reload} compact />}
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.matched} onChange={(p) => setPaging({ key, page: p })} />
        </>
      )}
    </div>
  );
};

/** The voter's own words on Snapshot. Long reasons fold; links are shown as text, not followed. */
const Reason: React.FC<{ text: string }> = ({ text }) => {
  const [open, setOpen] = useState(false);
  const long = text.length > 180;
  return (
    <p className="mt-1.5 text-xs text-[#4A463F] leading-snug break-words border-l-2 border-[#DDD5C7] pl-2">
      <span className="sr-only">Reason given: </span>&ldquo;{open || !long ? text : `${text.slice(0, 180).trimEnd()}…`}&rdquo;
      {long && (
        <button type="button" onClick={() => setOpen((o) => !o)} className="ml-1 underline underline-offset-2 cursor-pointer">
          {open ? 'less' : 'more'}
        </button>
      )}
    </p>
  );
};

const ChoiceButton: React.FC<{ active: boolean; onClick: () => void; children: React.ReactNode }> = ({ active, onClick, children }) => (
  <button
    type="button"
    aria-pressed={active}
    onClick={onClick}
    className={`max-w-[220px] truncate px-2.5 py-1 rounded-full text-xs border transition-colors cursor-pointer ${
      active ? 'bg-[#181715] text-[#FAF8F5] border-[#181715]' : 'bg-white text-[#4A463F] border-[#DDD5C7] hover:border-[#181715]'
    }`}
  >
    {children}
  </button>
);
