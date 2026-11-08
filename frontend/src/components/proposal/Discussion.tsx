import React, { useState } from 'react';
import { ExternalLink as ExternalIcon } from 'lucide-react';
import { api } from '../../api/endpoints';
import type { ForumPost, PostOrder } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { formatCompact, formatDateTime, formatInt, formatPct, truncateAddress } from '../../lib/format';
import { ConfidenceBadge } from '../ui/Badge';
import { Select } from '../ui/Field';
import { ExternalLink, Link } from '../ui/Link';
import { Pagination } from '../ui/Pagination';
import { EmptyState, ErrorState, LoadingBlock } from '../ui/States';
import { VoteChip } from './VoteChip';

const PAGE_SIZE = 25;
const PREVIEW_CHARS = 900;

const ORDER_LABEL: Record<PostOrder, string> = {
  thread: 'Forum order',
  voting_power: 'Biggest voters first',
  newest: 'Newest first',
};

/**
 * The proposal's forum thread (GET /proposals/{id}/posts), read in full on this page.
 * Each post shows what its author voted and with how much power, when we could link the
 * forum username to a wallet: what people said, next to what they did.
 */
export const Discussion: React.FC<{ proposalId: string; discussionUrl: string | null }> = ({ proposalId, discussionUrl }) => {
  const [order, setOrder] = useState<PostOrder>('thread');
  const [paging, setPaging] = useState({ order, page: 0 });
  const page = paging.order === order ? paging.page : 0;
  const state = useAsync(
    (signal) => api.proposalPosts(proposalId, { limit: PAGE_SIZE, offset: page * PAGE_SIZE, order }, { signal }),
    [proposalId, page, order],
    { keepPrevious: true },
  );
  const data = state.data;

  if (state.error && !data) return <ErrorState error={state.error} onRetry={state.reload} compact />;
  if (!data) return <LoadingBlock label="Loading the discussion" rows={8} />;
  if (data.total === 0) {
    return (
      <EmptyState
        title="No forum discussion stored"
        description={
          discussionUrl ? (
            <>
              We hold no posts for this proposal yet.{' '}
              <ExternalLink href={discussionUrl} className="underline">
                Open the forum thread ↗
              </ExternalLink>
            </>
          ) : (
            'This proposal does not link a forum thread.'
          )
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-[#4A463F]">
          <strong>{formatInt(data.total)}</strong> posts by <strong>{formatInt(data.posters)}</strong> people.{' '}
          <span className="text-[#5C5852]">
            For {formatInt(data.posts_with_vote)} of them we can show how the author voted.
          </span>
        </p>
        <Select aria-label="Order posts" value={order} onChange={(e) => setOrder(e.target.value as PostOrder)}>
          {(Object.keys(ORDER_LABEL) as PostOrder[]).map((o) => (
            <option key={o} value={o}>
              {ORDER_LABEL[o]}
            </option>
          ))}
        </Select>
      </div>

      <ol className={`space-y-3 transition-opacity ${state.loading ? 'opacity-60' : ''}`}>
        {data.posts.map((p) => (
          <li key={p.post_id}>
            <PostCard post={p} />
          </li>
        ))}
      </ol>
      {state.error && <ErrorState error={state.error} onRetry={state.reload} compact />}
      <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={(n) => setPaging({ order, page: n })} />
      <p className="text-[11px] text-[#7D776E]">
        A vote is shown only when the forum username is linked to a wallet (the badge says how sure the link is). No vote
        shown does not mean the person did not vote: only some forum users can be matched.
      </p>
    </div>
  );
};

const PostCard: React.FC<{ post: ForumPost }> = ({ post: p }) => {
  const [open, setOpen] = useState(false);
  const long = p.content.length > PREVIEW_CHARS;
  const text = open || !long ? p.content : `${p.content.slice(0, PREVIEW_CHARS).trimEnd()}…`;
  return (
    <article className="rounded-xl border border-[#E8E2D8] bg-white p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="w-8 h-8 shrink-0 rounded-full bg-[#F0ECE3] text-[#4A463F] flex items-center justify-center text-xs font-semibold uppercase" aria-hidden>
            {p.username.slice(0, 2)}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              {p.author ? (
                <Link to={`/person/${encodeURIComponent(p.username.toLowerCase())}`} className="font-semibold text-sm text-[#181715] hover:underline">
                  {p.username}
                </Link>
              ) : (
                <span className="font-semibold text-sm text-[#181715]">{p.username}</span>
              )}
              {p.author?.ens_name && <span className="text-xs text-[#5C5852]">{p.author.ens_name}</span>}
              {p.author && !p.author.ens_name && (
                <span className="font-mono text-[11px] text-[#7D776E]" title={p.author.wallet_address}>
                  {truncateAddress(p.author.wallet_address, 4)}
                </span>
              )}
              {p.author && <ConfidenceBadge level={p.author.confidence_level} />}
            </div>
            <div className="text-[11px] text-[#7D776E]">
              #{p.post_number ?? '—'} · {formatDateTime(p.created_at)}
            </div>
          </div>
        </div>
        <VoteContext post={p} />
      </header>

      {p.vote?.reason && (
        <p className="mt-3 rounded-md bg-[#FAF8F5] border border-[#E8E2D8] px-3 py-2 text-xs text-[#4A463F] break-words">
          <span className="editorial-label text-[9px] mr-1.5">Reason given with their vote</span>&ldquo;{p.vote.reason}&rdquo;
        </p>
      )}
      <div className="mt-3 text-[0.95rem] leading-relaxed text-[#2A2825] whitespace-pre-wrap break-words">{text}</div>

      <footer className="mt-3 flex flex-wrap items-center gap-4 text-xs">
        {long && (
          <button type="button" onClick={() => setOpen((o) => !o)} className="font-medium text-[#181715] underline underline-offset-2 cursor-pointer">
            {open ? 'Show less' : 'Read the whole post'}
          </button>
        )}
        {p.post_url && (
          <ExternalLink href={p.post_url} className="inline-flex items-center gap-1 text-[#5C5852] hover:text-[#181715]">
            On the forum <ExternalIcon size={11} aria-hidden />
          </ExternalLink>
        )}
      </footer>
    </article>
  );
};

/** What the author did on this proposal: their vote and voting power, or why we cannot say. */
const VoteContext: React.FC<{ post: ForumPost }> = ({ post: p }) => {
  if (p.vote) {
    return (
      <div className="text-right space-y-1">
        <div className="text-[10px] editorial-label">Voted</div>
        <VoteChip choice={p.vote.choice} />
        <div className="font-mono text-[11px] text-[#5C5852]">
          {formatCompact(p.vote.voting_power)} power · {formatPct(p.vote.power_share_pct)}
        </div>
      </div>
    );
  }
  return (
    <span className="text-[11px] text-[#8C867D]" title={p.author ? 'The linked wallet has no vote on this proposal.' : 'We could not link this forum user to a wallet.'}>
      {p.author ? 'Linked wallet did not vote' : 'No wallet link'}
    </span>
  );
};
