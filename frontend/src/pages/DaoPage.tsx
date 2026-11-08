import React, { useState } from 'react';
import { ArrowLeft, ExternalLink as ExternalIcon, MessageSquareText } from 'lucide-react';
import { getProposalCatalogue } from '../api/catalogue';
import { api } from '../api/endpoints';
import { ProposalExplorer } from '../components/proposal/ProposalExplorer';
import { Button } from '../components/ui/Button';
import { ExternalLink, Link } from '../components/ui/Link';
import { AsyncBoundary, ErrorState, LoadingBlock } from '../components/ui/States';
import { useAnalyst, useAnalystPageScope } from '../context/AnalystContext';
import { useDaos } from '../context/DaosContext';
import { useAsync } from '../hooks/useAsync';
import { chainName, daoMeta } from '../lib/daoMeta';
import { formatInt } from '../lib/format';
import { DEFAULT_FILTERS, type ExplorerFilters } from '../lib/proposals';

/** One DAO: what it is, and its proposals (newest first, filterable). */
export const DaoPage: React.FC<{ spaceId: string }> = ({ spaceId }) => {
  const { daos } = useDaos();
  const dao = useAsync((signal) => api.getDao(spaceId, { signal }), [spaceId]);
  const catalogue = useAsync(() => getProposalCatalogue(), []);
  const [filters, setFilters] = useState<ExplorerFilters>(DEFAULT_FILTERS);

  const { open: openAnalyst } = useAnalyst();
  useAnalystPageScope(dao.data ? { dao: { id: dao.data.id, name: dao.data.name } } : null);
  const meta = daoMeta(spaceId, dao.data?.name);

  return (
    <div className="quorum-container py-8 sm:py-10 space-y-8 animate-fade-in">
      <Link to="/daos" className="inline-flex items-center gap-1.5 text-xs text-[#5C5852] hover:text-[#181715]">
        <ArrowLeft size={13} aria-hidden /> All DAOs
      </Link>

      <AsyncBoundary state={dao} label="Loading DAO" skeleton={<LoadingBlock label="Loading DAO" rows={3} />}>
        {(d) => (
          <header className="flex flex-wrap items-end justify-between gap-4">
            <div className="max-w-3xl">
              <div className="editorial-label text-[#8C867D] mb-1.5">
                {chainName(d.network)} · {meta.symbol}
              </div>
              <h1 className="editorial-headline text-3xl sm:text-4xl text-[#181715]">{d.name}</h1>
              {d.about && <p className="text-sm text-[#4A463F] mt-2 leading-relaxed">{d.about}</p>}
              <p className="text-xs text-[#5C5852] mt-2">
                {formatInt(d.proposals_ingested)} proposals stored · {formatInt(d.proposals_with_forum)} with forum discussion
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="primary" icon={<MessageSquareText size={14} />} onClick={() => openAnalyst()}>
                Ask about {d.name}
              </Button>
              <ExternalLink
                href={d.space_snapshot_url}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-md border border-[#DDD5C7] bg-white hover:bg-[#FAF8F5]"
              >
                Snapshot space <ExternalIcon size={12} aria-hidden />
              </ExternalLink>
            </div>
          </header>
        )}
      </AsyncBoundary>

      {catalogue.error ? (
        <ErrorState error={catalogue.error} onRetry={catalogue.reload} />
      ) : !catalogue.data ? (
        <LoadingBlock label="Loading proposals" rows={5} />
      ) : (
        <ProposalExplorer proposals={catalogue.data} daos={daos} lockedDao={spaceId} value={filters} onChange={setFilters} />
      )}
    </div>
  );
};
