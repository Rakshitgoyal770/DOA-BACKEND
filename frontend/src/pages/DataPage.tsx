import React, { useMemo } from 'react';
import { CheckCircle2, CircleAlert } from 'lucide-react';
import { getProposalCatalogue } from '../api/catalogue';
import { getSyncStatus, lastSyncActivity } from '../api/freshness';
import { PageHeader, Section } from '../components/layout/PageHeader';
import { Button } from '../components/ui/Button';
import { MetricCard } from '../components/ui/MetricCard';
import { AsyncBoundary } from '../components/ui/States';
import { useAsync } from '../hooks/useAsync';
import { daoMeta } from '../lib/daoMeta';
import { deriveStatus } from '../lib/status';
import { daysSince, formatAgo, formatDateTime, formatInt } from '../lib/format';

/**
 * What data the database holds and how fresh it is (GET /sync/status). Read-only.
 * The per-DAO status column uses the same rule as every other screen (lib/status.ts): a
 * proposal synced as "active" whose voting window has closed is counted as ended, not open.
 */
export const DataPage: React.FC = () => {
  const [force, setForce] = React.useState(0);
  const status = useAsync(() => getSyncStatus(force > 0), [force]);
  const catalogue = useAsync(() => getProposalCatalogue(), []);
  // space id -> counts by the status the UI shows (open / ended but not re-synced / closed)
  const live = useMemo(() => {
    const m = new Map<string, { open: number; ended: number; closed: number }>();
    for (const p of catalogue.data ?? []) {
      const c = m.get(p.space_id) ?? { open: 0, ended: 0, closed: 0 };
      const s = deriveStatus(p);
      if (s === 'ended') c.ended += 1;
      else if (s === 'closed') c.closed += 1;
      else c.open += 1;
      m.set(p.space_id, c);
    }
    return m;
  }, [catalogue.data]);

  return (
    <div className="quorum-container py-8 sm:py-10 space-y-8 animate-fade-in">
      <PageHeader
        eyebrow="Transparency"
        title="Data coverage"
        description="What the database contains, how fresh it is, and where it is incomplete. Every figure on this site comes from this data."
        actions={
          <Button variant="outline" loading={status.loading} onClick={() => setForce((n) => n + 1)}>
            Refresh
          </Button>
        }
      />

      <AsyncBoundary state={status} label="Auditing data (this takes a couple of seconds)">
        {(s) => {
          const newest = lastSyncActivity(s);
          const stale = daysSince(newest) > 3;
          const names = new Map(s.spaces.map((x) => [x.id, x.name]));
          const votesOk = s.votes.completeness.is_complete;
          const forumOk = s.forum.completeness.is_complete;
          return (
            <>
              {stale && newest && (
                <div role="note" className="rounded-lg border border-[#F5DCB5] bg-[#FEF6EA] text-[#8C5814] p-4 text-sm">
                  The last sync wrote data <strong>{formatAgo(newest)}</strong> ({formatDateTime(newest)}). Proposals that were open then may have ended since, and new proposals are missing until the next sync.
                </div>
              )}

              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <MetricCard label="Proposals" value={formatInt(s.total_proposals)} subtext={`${s.daos.length} DAOs`} />
                <MetricCard label="Votes" value={formatInt(s.votes.total_votes)} subtext={`${s.votes.proposals_with_votes} proposals · ${s.votes.date_range}`} />
                <MetricCard label="Forum posts" value={formatInt(s.forum.total_posts)} subtext={`${s.forum.proposals_with_posts} proposals · ${s.forum.date_range}. A post in a thread shared by two proposals counts once for each.`} />
                <MetricCard label="Audit run" value={<span className="text-lg">{formatDateTime(s.audit_timestamp)}</span>} subtext="When this report was generated" />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Section title="Vote completeness" hint="Stored votes versus the count Snapshot reports for each proposal.">
                  <Completeness
                    ok={votesOk}
                    lines={[
                      ['Complete', s.votes.completeness.complete],
                      ['Partial', s.votes.completeness.partial],
                      ['Missing', s.votes.completeness.missing],
                      ['No votes on Snapshot', s.votes.completeness.no_votes_on_snapshot],
                    ]}
                    fetched={s.votes.last_fetched}
                  />
                </Section>
                <Section title="Forum completeness" hint="Stored posts versus what each Discourse thread lists.">
                  <Completeness
                    ok={forumOk}
                    lines={[
                      ['Threads', s.forum.completeness.threads],
                      ['Complete', s.forum.completeness.complete],
                      ['Partial', s.forum.completeness.partial],
                      ['Not fetched', s.forum.completeness.not_fetched],
                      ['Fetch errors', s.forum.completeness.error],
                      ['Proposals without posts', s.forum.proposals_missing_posts],
                    ]}
                    fetched={s.forum.last_fetched}
                  />
                </Section>
              </div>

              <Section title="By DAO" hint="Date range is when each stored proposal started. A short range means we hold only that DAO's most recent proposals. 'Ended' proposals were stored while voting was open; their final tallies arrive with the next sync.">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm min-w-[620px]">
                    <caption className="sr-only">Stored data per DAO</caption>
                    <thead>
                      <tr className="text-left border-b border-[#E8E2D8]">
                        <th scope="col" className="editorial-label text-[9px] py-2 pr-3">DAO</th>
                        <th scope="col" className="editorial-label text-[9px] py-2 pr-3">Proposals</th>
                        <th scope="col" className="editorial-label text-[9px] py-2 pr-3" title="Open = voting still running now. Ended = synced while open, voting has since closed, final result not re-synced.">Open / ended / closed</th>
                        <th scope="col" className="editorial-label text-[9px] py-2 pr-3">With forum link</th>
                        <th scope="col" className="editorial-label text-[9px] py-2 pr-3">Date range</th>
                        <th scope="col" className="editorial-label text-[9px] py-2">Last fetched</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.daos.map((d) => (
                        <tr key={d.space_id} className="border-b border-[#F0ECE3]">
                          <td className="py-2.5 pr-3 font-medium">
                            <span className="inline-flex items-center gap-2">
                              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: daoMeta(d.space_id).color }} aria-hidden />
                              {names.get(d.space_id) ?? d.space_id}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3 font-mono text-xs">{d.count}</td>
                          <td className="py-2.5 pr-3 font-mono text-xs">
                            {live.get(d.space_id)
                              ? `${live.get(d.space_id)!.open} / ${live.get(d.space_id)!.ended} / ${live.get(d.space_id)!.closed}`
                              : `${d.active_count} / — / ${d.closed_count}`}
                          </td>
                          <td className="py-2.5 pr-3 font-mono text-xs">{d.with_forum_url}</td>
                          <td className="py-2.5 pr-3 font-mono text-xs whitespace-nowrap">{d.date_range}</td>
                          <td className="py-2.5 text-xs text-[#4A463F] whitespace-nowrap">{formatDateTime(d.last_fetched)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>

              <p className="text-xs text-[#7D776E] max-w-3xl leading-relaxed">
                This site only reads data. Refreshing the database (fetching new proposals, votes and posts) is an operator task run on the backend, not something
                visitors can trigger from here.
              </p>
            </>
          );
        }}
      </AsyncBoundary>
    </div>
  );
};

const Completeness: React.FC<{ ok: boolean; lines: [string, number][]; fetched: string }> = ({ ok, lines, fetched }) => (
  <div className="space-y-3">
    <div className={`flex items-center gap-2 text-sm font-medium ${ok ? 'text-[#23593F]' : 'text-[#8C5814]'}`}>
      {ok ? <CheckCircle2 size={16} aria-hidden /> : <CircleAlert size={16} aria-hidden />}
      {ok ? 'Complete' : 'Some gaps'}
    </div>
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
      {lines.map(([label, n]) => (
        <div key={label} className="flex justify-between border-b border-[#F0ECE3] py-1">
          <dt className="text-[#5C5852]">{label}</dt>
          <dd className="font-mono">{formatInt(n)}</dd>
        </div>
      ))}
    </dl>
    <p className="text-[11px] text-[#7D776E]">Last fetched {formatDateTime(fetched)}</p>
  </div>
);
