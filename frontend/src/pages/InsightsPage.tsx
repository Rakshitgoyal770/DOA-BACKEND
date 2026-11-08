import React, { useMemo } from 'react';
import { getProposalCatalogue } from '../api/catalogue';
import type { ProposalSummary } from '../api/types';
import { PageHeader, Section } from '../components/layout/PageHeader';
import { Link } from '../components/ui/Link';
import { Meter } from '../components/ui/Meter';
import { ErrorState, LoadingBlock } from '../components/ui/States';
import { useDaos } from '../context/DaosContext';
import { useAsync } from '../hooks/useAsync';
import { daoMeta } from '../lib/daoMeta';
import { formatInt, formatPct } from '../lib/format';

/** Ignore tiny votes when ranking by ratios: 1 poster / 3 voters is not a finding. */
const MIN_VOTERS = 100;
const TOP = 6;

/** Cross-DAO comparison, computed from GET /daos and the proposal catalogue. */
export const InsightsPage: React.FC = () => {
  const { daos, error: daoError, reload: reloadDaos, nameOf } = useDaos();
  const catalogue = useAsync(() => getProposalCatalogue(), []);

  const ranked = useMemo(() => {
    const big = (catalogue.data ?? []).filter((p) => (p.votes_count ?? 0) >= MIN_VOTERS);
    const by = (key: (p: ProposalSummary) => number, dir: 1 | -1) => [...big].sort((a, b) => dir * (key(a) - key(b))).slice(0, TOP);
    return {
      eligible: big.length,
      quietest: by((p) => p.silence_ratio_pct ?? Infinity, 1).filter((p) => p.silence_ratio_pct !== null),
      oneSided: by((p) => p.top_choice_share_pct ?? -1, -1).filter((p) => p.top_choice_share_pct !== null),
      mostDiscussed: by((p) => p.forum_posters, -1),
    };
  }, [catalogue.data]);

  return (
    <div className="quorum-container py-8 sm:py-10 space-y-8 animate-fade-in">
      <PageHeader
        eyebrow="Across protocols"
        title="Insights"
        description="How much deliberation sits behind on-chain votes, and how one-sided those votes are, compared across DAOs."
      />

      {daoError ? (
        <ErrorState error={daoError} onRetry={reloadDaos} />
      ) : !daos ? (
        <LoadingBlock label="Loading DAO comparison" rows={5} />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <CompareCard
            title="Forum coverage"
            hint="Share of proposals with any forum discussion."
            rows={daos.map((d) => ({ id: d.id, name: d.name, value: d.forum_coverage_pct }))}
          />
          <CompareCard
            title="Average silence ratio"
            hint="Forum posters ÷ voters, averaged over proposals. Lower = fewer people deliberate relative to voters."
            rows={daos.map((d) => ({ id: d.id, name: d.name, value: d.avg_silence_ratio_pct }))}
            scaleMax={Math.max(...daos.map((d) => d.avg_silence_ratio_pct), 1)}
          />
          <CompareCard
            title="Average top-choice share"
            hint="The winning choice's share of voting power. Near 100% = a lopsided vote."
            rows={daos.map((d) => ({ id: d.id, name: d.name, value: d.avg_top_choice_share_pct }))}
          />
        </div>
      )}

      {catalogue.error ? (
        <ErrorState error={catalogue.error} onRetry={catalogue.reload} />
      ) : !catalogue.data ? (
        <LoadingBlock label="Ranking proposals" rows={5} />
      ) : (
        <>
          <p className="text-xs text-[#7D776E]">
            Rankings below consider the {ranked.eligible} proposals with at least {MIN_VOTERS} voters, so tiny votes do not distort the ratios.
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <RankCard
              title="Least deliberated"
              hint="Lowest silence ratio: the most voters per forum poster."
              items={ranked.quietest}
              nameOf={nameOf}
              figure={(p) => `${formatPct(p.silence_ratio_pct)} · ${p.forum_posters} posters / ${formatInt(p.votes_count)} voters`}
            />
            <RankCard
              title="Most one-sided"
              hint="Highest share of voting power on one choice."
              items={ranked.oneSided}
              nameOf={nameOf}
              figure={(p) => `${formatPct(p.top_choice_share_pct)} on the top choice`}
            />
            <RankCard
              title="Most discussed"
              hint="Most distinct forum posters."
              items={ranked.mostDiscussed}
              nameOf={nameOf}
              figure={(p) => `${p.forum_posters} posters · ${formatInt(p.votes_count)} voters`}
            />
          </div>
        </>
      )}
    </div>
  );
};

const CompareCard: React.FC<{
  title: string;
  hint: string;
  rows: { id: string; name: string; value: number }[];
  scaleMax?: number;
}> = ({ title, hint, rows, scaleMax = 100 }) => (
  <Section title={title} hint={hint}>
    <ul className="space-y-4">
      {[...rows]
        .sort((a, b) => b.value - a.value)
        .map((r) => (
          <li key={r.id}>
            <div className="flex items-baseline justify-between text-sm mb-1">
              <Link to={`/dao/${encodeURIComponent(r.id)}`} className="font-medium hover:underline">
                {r.name}
              </Link>
              <span className="font-mono text-xs">{formatPct(r.value)}</span>
            </div>
            <Meter value={(r.value / scaleMax) * 100} color={daoMeta(r.id, r.name).color} label={`${r.name}: ${formatPct(r.value)}`} />
          </li>
        ))}
    </ul>
  </Section>
);

const RankCard: React.FC<{
  title: string;
  hint: string;
  items: ProposalSummary[];
  nameOf: (id: string) => string;
  figure: (p: ProposalSummary) => string;
}> = ({ title, hint, items, nameOf, figure }) => (
  <Section title={title} hint={hint}>
    {items.length === 0 ? (
      <p className="text-sm text-[#5C5852]">Not enough data.</p>
    ) : (
      <ol className="space-y-3">
        {items.map((p, i) => (
          <li key={p.id} className="flex gap-3">
            <span className="font-mono text-xs text-[#8C867D] mt-0.5 w-4 shrink-0">{i + 1}</span>
            <div className="min-w-0">
              <Link to={`/proposal/${encodeURIComponent(p.id)}`} className="text-sm font-medium hover:underline break-words">
                {p.title}
              </Link>
              <div className="text-[11px] text-[#7D776E] mt-0.5">
                <span className="font-semibold text-[#4A463F]">{nameOf(p.space_id)}</span> · {figure(p)}
              </div>
            </div>
          </li>
        ))}
      </ol>
    )}
  </Section>
);
