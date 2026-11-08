import React, { Suspense, lazy } from 'react';
import { ArrowLeft, ExternalLink as ExternalIcon, MessageSquareText } from 'lucide-react';
import { api } from '../api/endpoints';
import { BiggestVoters } from '../components/proposal/BiggestVoters';
import { Discussion } from '../components/proposal/Discussion';
import { ResultByChoice } from '../components/proposal/ResultByChoice';
import { VotesTable } from '../components/proposal/VotesTable';
import { StatusBadge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { ExternalLink, Link } from '../components/ui/Link';
import { AsyncBoundary, LoadingBlock } from '../components/ui/States';
import { useAnalyst, useAnalystPageScope } from '../context/AnalystContext';
import { useDaos } from '../context/DaosContext';
import { useAsync } from '../hooks/useAsync';
import { href, navigate, useRoute } from '../hooks/useRouter';
import { daoMeta } from '../lib/daoMeta';
import { formatCompact, formatDate, formatInt, formatTimeRemaining, truncateAddress } from '../lib/format';
import { STATUS_HINT, deriveStatus, isVotable } from '../lib/status';

// The markdown renderer is only needed here, so it loads with the first proposal page, not with the app.
const ProposalBody = lazy(() => import('../components/proposal/ProposalBody').then((m) => ({ default: m.ProposalBody })));

type Tab = 'text' | 'votes' | 'discussion';
const TABS: Tab[] = ['text', 'votes', 'discussion'];

/**
 * One proposal, completely: what it asks for (full text), how it is being decided (result and
 * every vote) and what people argued (the forum thread, each post next to its author's vote).
 * The open tab lives in the URL (?tab=votes), so a view can be shared.
 */
export const ProposalPage: React.FC<{ proposalId: string }> = ({ proposalId }) => {
  const { nameOf } = useDaos();
  const { open: openAnalyst } = useAnalyst();
  const route = useRoute();
  const tab: Tab = TABS.find((t) => t === route.query.get('tab')) ?? 'text';
  const setTab = (t: Tab) => navigate(href(`/proposal/${encodeURIComponent(proposalId)}`, { tab: t === 'text' ? null : t }), { replace: true });

  const proposal = useAsync((signal) => api.getProposal(proposalId, { signal }), [proposalId]);
  const participants = useAsync((signal) => api.proposalParticipants(proposalId, { signal }), [proposalId]);
  // the five largest votes, with ENS names and forum links (GET /votes sorts by voting power)
  const topVotes = useAsync((signal) => api.proposalVotes(proposalId, { limit: 5 }, { signal }), [proposalId]);

  // "Ask about this proposal" (here and in the nav) opens the analyst focused on it.
  useAnalystPageScope(
    proposal.data
      ? { proposal: { id: proposal.data.id, title: proposal.data.title }, dao: { id: proposal.data.space_id, name: nameOf(proposal.data.space_id) } }
      : null,
  );

  return (
    <div className="quorum-container py-8 sm:py-10 space-y-8 animate-fade-in">
      <Link to="/" className="inline-flex items-center gap-1.5 text-xs text-[#5C5852] hover:text-[#181715]">
        <ArrowLeft size={13} aria-hidden /> All proposals
      </Link>

      <AsyncBoundary state={proposal} label="Loading proposal" skeleton={<LoadingBlock label="Loading proposal" rows={8} />}>
        {(p) => {
          const status = deriveStatus(p);
          const meta = daoMeta(p.space_id, nameOf(p.space_id));
          return (
            <>
              <header className="space-y-4 max-w-4xl">
                <div className="flex flex-wrap items-center gap-3">
                  <Link to={`/dao/${encodeURIComponent(p.space_id)}`} className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#4A463F] hover:underline">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: meta.color }} aria-hidden />
                    {nameOf(p.space_id)}
                  </Link>
                  <StatusBadge status={status} size="md" />
                  <span className="text-xs font-mono text-[#7D776E]">
                    {formatDate(p.start_ts)} → {formatDate(p.end_ts)}
                    {status === 'active' && ` · ${formatTimeRemaining(p.end_ts)}`}
                  </span>
                </div>
                <h1 className="editorial-headline text-3xl sm:text-4xl text-[#181715] break-words">{p.title}</h1>
                <div className="flex flex-wrap items-center gap-x-5 gap-y-3 text-xs text-[#5C5852]">
                  {p.author && (
                    <span>
                      Proposed by{' '}
                      <ExternalLink href={`https://snapshot.org/#/profile/${p.author}`} className="font-mono underline underline-offset-2" title={p.author}>
                        {truncateAddress(p.author, 5)}
                      </ExternalLink>
                    </span>
                  )}
                  <span>
                    <strong className="text-[#181715]">{formatInt(p.votes_count)}</strong> voters
                  </span>
                  <span>
                    <strong className="text-[#181715]">{formatInt(p.forum_posters)}</strong> people in the discussion
                  </span>
                  {p.link && (
                    <ExternalLink href={p.link} className="inline-flex items-center gap-1 underline underline-offset-2">
                      Snapshot <ExternalIcon size={11} aria-hidden />
                    </ExternalLink>
                  )}
                  {p.discussion_url && (
                    <ExternalLink href={p.discussion_url} className="inline-flex items-center gap-1 underline underline-offset-2">
                      Forum thread <ExternalIcon size={11} aria-hidden />
                    </ExternalLink>
                  )}
                </div>
              </header>

              {isVotable(status) && p.link && (
                <div className="rounded-lg border border-[#BCD9E7] bg-[#E8F2F7] text-[#143A4D] p-4 text-sm flex flex-wrap items-center justify-between gap-3">
                  <span>
                    <strong>Voting is open.</strong> Votes are cast on Snapshot by the wallet that holds the voting power; this site only reads.
                  </span>
                  <ExternalLink href={p.link} className="px-4 py-2 rounded-md bg-[#143A4D] text-white text-xs font-semibold hover:bg-[#0F2D3B] whitespace-nowrap">
                    Vote on Snapshot ↗
                  </ExternalLink>
                </div>
              )}
              {STATUS_HINT[status] && (
                <div role="note" className="rounded-lg border border-[#F5DCB5] bg-[#FEF6EA] text-[#8C5814] p-4 text-sm">
                  {STATUS_HINT[status]}
                </div>
              )}

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
                <div className="lg:col-span-2 min-w-0 space-y-4">
                  <div className="lg:hidden">
                    <SideCard title={status === 'active' ? 'Current result' : 'Result'}>
                      <ResultByChoice choices={p.choices} scores={p.scores} scoresTotal={p.scores_total} open={status === 'active'} />
                    </SideCard>
                  </div>
                  <div role="tablist" aria-label="Proposal sections" className="flex gap-1 border-b border-[#E8E2D8] overflow-x-auto">
                    <TabButton id="text" active={tab === 'text'} onClick={() => setTab('text')}>
                      The proposal
                    </TabButton>
                    <TabButton id="votes" active={tab === 'votes'} onClick={() => setTab('votes')}>
                      Votes <Count n={p.votes_ingested} />
                    </TabButton>
                    <TabButton id="discussion" active={tab === 'discussion'} onClick={() => setTab('discussion')}>
                      Discussion <Count n={p.forum_posters} />
                    </TabButton>
                  </div>
                  <section role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="rounded-xl bg-white border border-[#E8E2D8] p-5 sm:p-7">
                    {tab === 'text' && typeof p.body !== 'string' && (
                      <div className="space-y-4">
                        <div role="alert" className="rounded-lg border border-[#F2C5BC] bg-[#FCEEEA] text-[#8E2F20] p-4 text-sm">
                          <strong>This is only the first 500 characters.</strong> The data service is older than this site and does not send the complete text.
                          Restart the backend with the latest code (<code>uvicorn main:app --port 8000</code>), then reload.
                        </div>
                        <p className="whitespace-pre-wrap break-words text-sm text-[#4A463F]">{p.body_preview}</p>
                      </div>
                    )}
                    {tab === 'text' && typeof p.body === 'string' && (
                      <Suspense fallback={<LoadingBlock label="Loading the proposal text" rows={6} />}>
                        <ProposalBody markdown={p.body} />
                      </Suspense>
                    )}
                    {tab === 'votes' && <VotesTable proposalId={p.id} choices={p.choices} />}
                    {tab === 'discussion' && <Discussion proposalId={p.id} discussionUrl={p.discussion_url} />}
                  </section>
                </div>

                <aside className="space-y-6 min-w-0 lg:sticky lg:top-20">
                  <SideCard title={status === 'active' ? 'Current result' : 'Result'} className="hidden lg:block">
                    <ResultByChoice choices={p.choices} scores={p.scores} scoresTotal={p.scores_total} open={status === 'active'} />
                    <p className="mt-4 text-xs text-[#5C5852]">
                      {formatInt(p.votes_count)} voters · {formatCompact(p.scores_total)} voting power in total.{' '}
                      <button type="button" onClick={() => setTab('votes')} className="underline underline-offset-2 cursor-pointer">
                        See every vote
                      </button>
                    </p>
                  </SideCard>

                  <SideCard title="Did the biggest voters speak?">
                    {topVotes.data && topVotes.data.stored_votes === 0 ? (
                      <p className="text-sm text-[#5C5852]">No individual votes are stored for this proposal yet.</p>
                    ) : topVotes.data && participants.data ? (
                      <BiggestVoters votes={topVotes.data.votes} participants={participants.data} onShowDiscussion={() => setTab('discussion')} />
                    ) : topVotes.error || participants.error ? (
                      <p className="text-sm text-[#5C5852]">Could not load the voters or the discussion. Try again later.</p>
                    ) : (
                      <LoadingBlock label="Loading the biggest voters" rows={4} />
                    )}
                  </SideCard>

                  <SideCard title="Ask about this proposal">
                    <p className="text-sm text-[#4A463F] mb-3">
                      Get a sourced answer from this proposal&apos;s text, votes and discussion: what it asks for, who argued against it, how the biggest voters voted.
                    </p>
                    <Button variant="primary" icon={<MessageSquareText size={14} />} onClick={() => openAnalyst()}>
                      Ask about this proposal
                    </Button>
                  </SideCard>
                </aside>
              </div>
            </>
          );
        }}
      </AsyncBoundary>
    </div>
  );
};

const TabButton: React.FC<{ id: Tab; active: boolean; onClick: () => void; children: React.ReactNode }> = ({ id, active, onClick, children }) => (
  <button
    type="button"
    role="tab"
    id={`tab-${id}`}
    aria-selected={active}
    aria-controls={`panel-${id}`}
    onClick={onClick}
    className={`px-4 py-2.5 text-sm whitespace-nowrap border-b-2 -mb-px transition-colors cursor-pointer ${
      active ? 'border-[#181715] text-[#181715] font-semibold' : 'border-transparent text-[#5C5852] hover:text-[#181715]'
    }`}
  >
    {children}
  </button>
);

const Count: React.FC<{ n: number | null }> = ({ n }) => (
  <span className="ml-1 rounded-full bg-[#F0ECE3] px-1.5 py-0.5 text-[10px] font-mono text-[#4A463F]">{formatInt(n)}</span>
);

const SideCard: React.FC<{ title: string; children: React.ReactNode; className?: string }> = ({ title, children, className = '' }) => (
  <section className={`rounded-xl bg-white border border-[#E8E2D8] p-5 ${className}`}>
    <h2 className="editorial-label tracking-wider text-[#181715] mb-3">{title}</h2>
    {children}
  </section>
);
