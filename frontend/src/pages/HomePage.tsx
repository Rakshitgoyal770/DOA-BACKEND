import React, { useMemo } from 'react';
import { getProposalCatalogue } from '../api/catalogue';
import { getSyncStatus, lastSyncActivity } from '../api/freshness';
import { ProposalExplorer } from '../components/proposal/ProposalExplorer';
import { Link } from '../components/ui/Link';
import { ErrorState, LoadingBlock } from '../components/ui/States';
import { useDaos } from '../context/DaosContext';
import { useAsync } from '../hooks/useAsync';
import { href, navigate, useRoute } from '../hooks/useRouter';
import { formatAgo, formatDateTime } from '../lib/format';
import { filtersToParams, parseFilters, type ExplorerFilters } from '../lib/proposals';

/**
 * The landing page: every proposal across the DAOs we follow, newest first, with DAO chips
 * and status tabs. Filters live in the URL so a filtered view can be shared.
 */
export const HomePage: React.FC = () => {
  const route = useRoute();
  const { daos } = useDaos();
  const catalogue = useAsync(() => getProposalCatalogue(), []);
  const sync = useAsync(() => getSyncStatus(), []);
  const filters = useMemo(() => parseFilters(route.query), [route.query]);
  const asOf = lastSyncActivity(sync.data);
  const daoNames = daos?.map((d) => d.name).join(', ');

  const onChange = (next: ExplorerFilters) => navigate(href('/', filtersToParams(next)), { replace: true });

  return (
    <div className="quorum-container py-8 sm:py-10 space-y-6 animate-fade-in">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-3xl">
          <h1 className="editorial-headline text-3xl sm:text-4xl text-[#181715]">Governance proposals</h1>
          <p className="text-sm text-[#4A463F] mt-2 leading-relaxed">
            Each proposal in one place: the full text, every vote with its voting power, and the forum discussion, where we show how each speaker
            actually voted.{daoNames && <> Covering {daoNames}.</>}
          </p>
        </div>
        <p className="text-xs text-[#7D776E]">
          {asOf ? (
            <>
              Last synced {formatDateTime(asOf)} ({formatAgo(asOf)}).{' '}
              <Link to="/data" className="underline underline-offset-2">
                Coverage
              </Link>
            </>
          ) : sync.loading ? (
            'Checking data freshness…'
          ) : null}
        </p>
      </header>

      {catalogue.error ? (
        <ErrorState error={catalogue.error} onRetry={catalogue.reload} />
      ) : !catalogue.data ? (
        <LoadingBlock label="Loading proposals" rows={6} />
      ) : (
        <ProposalExplorer proposals={catalogue.data} daos={daos} value={filters} onChange={onChange} />
      )}
    </div>
  );
};
