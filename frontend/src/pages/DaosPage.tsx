import React, { useMemo } from 'react';
import { ArrowRight } from 'lucide-react';
import { getProposalCatalogue } from '../api/catalogue';
import type { DaoSummary, ProposalSummary } from '../api/types';
import { Link } from '../components/ui/Link';
import { ErrorState, Skeleton } from '../components/ui/States';
import { useDaos } from '../context/DaosContext';
import { useAsync } from '../hooks/useAsync';
import { chainName, daoMeta } from '../lib/daoMeta';
import { formatDate, formatInt } from '../lib/format';
import { deriveStatus } from '../lib/status';

/** The DAOs we follow, as a way into their proposals: what each one is, and what is happening there. */
export const DaosPage: React.FC = () => {
  const { daos, error, reload } = useDaos();
  const catalogue = useAsync(() => getProposalCatalogue(), []);
  const bySpace = useMemo(() => {
    const m = new Map<string, ProposalSummary[]>();
    for (const p of catalogue.data ?? []) m.set(p.space_id, [...(m.get(p.space_id) ?? []), p]);
    return m;
  }, [catalogue.data]);

  return (
    <div className="quorum-container py-8 sm:py-10 space-y-6 animate-fade-in">
      <header className="max-w-3xl">
        <h1 className="editorial-headline text-3xl sm:text-4xl text-[#181715]">DAOs</h1>
        <p className="text-sm text-[#4A463F] mt-2">Pick a DAO to see its proposals, newest first.</p>
      </header>
      {error ? (
        <ErrorState error={error} onRetry={reload} />
      ) : !daos ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-44 rounded-xl" />
          ))}
        </div>
      ) : (
        <ul className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {daos.map((d) => (
            <li key={d.id}>
              <DaoCard dao={d} proposals={bySpace.get(d.id)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

const DaoCard: React.FC<{ dao: DaoSummary; proposals: ProposalSummary[] | undefined }> = ({ dao, proposals }) => {
  const meta = daoMeta(dao.id, dao.name);
  const open = proposals?.filter((p) => deriveStatus(p) === 'active').length ?? 0;
  const latest = proposals?.reduce<ProposalSummary | null>((a, p) => (!a || (p.start_ts ?? 0) > (a.start_ts ?? 0) ? p : a), null);
  return (
    <Link
      to={`/dao/${encodeURIComponent(dao.id)}`}
      className="group h-full p-5 rounded-xl bg-white border border-[#E8E2D8] hover:border-[#181715] hover:shadow-card transition-all flex flex-col gap-4"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="w-9 h-9 rounded-xl flex items-center justify-center text-[11px] font-bold text-white" style={{ backgroundColor: meta.color }} aria-hidden>
            {meta.symbol.slice(0, 3)}
          </span>
          <h2 className="text-lg font-serif font-bold text-[#181715] group-hover:underline">{dao.name}</h2>
        </div>
        <span className="text-[10px] font-mono text-[#7D776E] bg-[#FAF8F5] px-2 py-0.5 rounded border border-[#E8E2D8]">{chainName(dao.network)}</span>
      </div>
      {dao.about && <p className="text-sm text-[#5C5852] line-clamp-2">{dao.about}</p>}
      <div className="mt-auto space-y-1 text-xs text-[#4A463F]">
        <div>
          <strong className="font-mono">{formatInt(dao.proposals_ingested)}</strong> proposals
          {open > 0 && <span className="text-[#164054] font-semibold"> · {open} open now</span>}
        </div>
        {latest && (
          <div className="truncate" title={latest.title}>
            Latest: {latest.title} <span className="text-[#7D776E]">({formatDate(latest.start_ts)})</span>
          </div>
        )}
      </div>
      <span className="inline-flex items-center gap-1 text-xs font-medium text-[#181715]">
        See proposals <ArrowRight size={13} aria-hidden />
      </span>
    </Link>
  );
};
