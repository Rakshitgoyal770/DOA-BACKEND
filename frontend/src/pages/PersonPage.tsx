import React, { useState } from 'react';
import { ArrowLeft, ChevronDown, ChevronRight, ExternalLink as ExternalIcon } from 'lucide-react';
import { api } from '../api/endpoints';
import type { ForumPost, IdentityDetail } from '../api/types';
import { VoteChip } from '../components/proposal/VoteChip';
import { ConfidenceBadge } from '../components/ui/Badge';
import { ExternalLink, Link } from '../components/ui/Link';
import { AsyncBoundary, EmptyState, ErrorState, LoadingBlock } from '../components/ui/States';
import { useAsync } from '../hooks/useAsync';
import { formatCompact, formatDateTime, formatInt, methodLabel } from '../lib/format';

/** GET /identities/{username} returns at most this many votes (features/identity/routes.py, LIMIT 25). */
const MAX_VOTES = 25;
const POSTS_PAGE = 200; // the posts endpoint's largest page

/**
 * One person: the wallet they vote with, their largest votes, and for each vote what they
 * wrote in that proposal's forum thread (loaded when opened).
 */
export const PersonPage: React.FC<{ username: string }> = ({ username }) => {
  const identity = useAsync((signal) => api.getIdentity(username, { signal }), [username]);

  return (
    <div className="quorum-container py-8 sm:py-10 space-y-8 animate-fade-in">
      <Link to="/people" className="inline-flex items-center gap-1.5 text-xs text-[#5C5852] hover:text-[#181715]">
        <ArrowLeft size={13} aria-hidden /> All people
      </Link>

      <AsyncBoundary state={identity} label="Loading person" skeleton={<LoadingBlock rows={6} />}>
        {(i) => (
          <>
            <header className="flex flex-wrap items-end justify-between gap-4">
              <div className="min-w-0">
                <h1 className="editorial-headline text-3xl sm:text-4xl text-[#181715] break-words">
                  @{i.forum_username}
                  {i.ens_name && <span className="text-[#5C5852] text-2xl"> · {i.ens_name}</span>}
                </h1>
                <p className="font-mono text-xs text-[#5C5852] mt-2 break-all">{i.wallet_address}</p>
                <p className="text-xs text-[#5C5852] mt-2 flex flex-wrap items-center gap-2">
                  <ConfidenceBadge level={i.confidence_level} /> matched by {methodLabel(i.resolution_method).toLowerCase()} · {formatInt(i.post_count)} forum posts
                </p>
              </div>
              <ExternalLink
                href={`https://snapshot.org/#/profile/${i.wallet_address}`}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-md border border-[#DDD5C7] bg-white hover:bg-[#FAF8F5]"
              >
                Snapshot profile <ExternalIcon size={12} aria-hidden />
              </ExternalLink>
            </header>

            <section aria-labelledby="votes-title" className="space-y-3">
              <div>
                <h2 id="votes-title" className="editorial-label tracking-wider text-[#181715]">
                  How they voted
                </h2>
                <p className="text-xs text-[#7D776E] mt-1">
                  {i.votes.length >= MAX_VOTES
                    ? `Their ${MAX_VOTES} votes with the most voting power, in the proposals we hold.`
                    : 'Every vote of theirs in the proposals we hold.'}{' '}
                  Open one to read what they wrote about it.
                </p>
              </div>
              {i.votes.length === 0 ? (
                <EmptyState title="No stored votes" description="This wallet has no votes in the proposals we hold." />
              ) : (
                <ul className="space-y-2">
                  {i.votes.map((v) => (
                    <VoteWithPosts key={v.proposal_id} username={i.forum_username} vote={v} />
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </AsyncBoundary>
    </div>
  );
};

const VoteWithPosts: React.FC<{ username: string; vote: IdentityDetail['votes'][number] }> = ({ username, vote }) => {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-xl border border-[#E8E2D8] bg-white">
      <div className="flex flex-wrap items-center gap-3 p-3 sm:p-4">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={open ? 'Hide what they wrote' : 'Show what they wrote'} className="p-1 rounded hover:bg-[#F4F0E8] cursor-pointer">
          {open ? <ChevronDown size={16} aria-hidden /> : <ChevronRight size={16} aria-hidden />}
        </button>
        <Link to={`/proposal/${encodeURIComponent(vote.proposal_id)}`} className="flex-1 min-w-[200px] text-sm font-medium text-[#181715] hover:underline break-words">
          {vote.title}
        </Link>
        <VoteChip choice={vote.choice} />
        <span className="font-mono text-xs text-[#4A463F] w-20 text-right">{formatCompact(vote.vp)}</span>
      </div>
      {open && (
        <div className="border-t border-[#F0ECE3] p-3 sm:p-4">
          <TheirPosts proposalId={vote.proposal_id} username={username} />
        </div>
      )}
    </li>
  );
};

/** Every post this person wrote in one proposal's thread (pages through GET /posts and keeps theirs). */
const TheirPosts: React.FC<{ proposalId: string; username: string }> = ({ proposalId, username }) => {
  const state = useAsync(
    async (signal) => {
      const mine: ForumPost[] = [];
      for (let offset = 0; ; offset += POSTS_PAGE) {
        const page = await api.proposalPosts(proposalId, { limit: POSTS_PAGE, offset }, { signal });
        mine.push(...page.posts.filter((p) => p.username.toLowerCase() === username.toLowerCase()));
        if (offset + POSTS_PAGE >= page.total) return mine;
      }
    },
    [proposalId, username],
  );
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} compact />;
  if (!state.data) return <LoadingBlock label="Loading their posts" rows={2} />;
  if (state.data.length === 0) return <p className="text-sm text-[#5C5852]">They did not post in this proposal&apos;s forum thread.</p>;
  return (
    <ol className="space-y-3">
      {state.data.map((p) => (
        <li key={p.post_id} className="text-sm">
          <div className="text-[11px] text-[#7D776E] mb-1 flex flex-wrap gap-3">
            <span>
              #{p.post_number ?? '—'} · {formatDateTime(p.created_at)}
            </span>
            {p.post_url && (
              <ExternalLink href={p.post_url} className="inline-flex items-center gap-1 hover:text-[#181715]">
                On the forum <ExternalIcon size={10} aria-hidden />
              </ExternalLink>
            )}
          </div>
          <p className="whitespace-pre-wrap break-words leading-relaxed text-[#2A2825]">{p.content}</p>
        </li>
      ))}
    </ol>
  );
};
