import React, { useCallback, useEffect, useState } from 'react';
import { clearCatalogueCache } from './api/catalogue';
import { clearSyncStatusCache } from './api/freshness';
import { AnalystPanel } from './components/analyst/AnalystPanel';
import { ConnectionBanner } from './components/layout/ConnectionBanner';
import { TopNav } from './components/layout/TopNav';
import { SearchModal } from './components/search/SearchModal';
import { Link } from './components/ui/Link';
import { AnalystProvider, useAnalyst } from './context/AnalystContext';
import { DaosProvider, useDaos } from './context/DaosContext';
import { useRoute, type Route } from './hooks/useRouter';
import { DaoPage } from './pages/DaoPage';
import { DaosPage } from './pages/DaosPage';
import { DataPage } from './pages/DataPage';
import { HomePage } from './pages/HomePage';
import { InsightsPage } from './pages/InsightsPage';
import { MethodologyPage } from './pages/MethodologyPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { PeoplePage } from './pages/PeoplePage';
import { PersonPage } from './pages/PersonPage';
import { ProposalPage } from './pages/ProposalPage';

/**
 * Map the URL to a page and to the nav item that should be highlighted.
 * Older addresses keep working: /proposals, /identities and /identity/{name} lead to the new pages.
 */
function resolve(route: Route): { key: string; page: React.ReactNode } {
  const [first, second] = route.segments;
  switch (first) {
    case undefined:
    case 'proposals':
      return { key: 'proposals', page: <HomePage /> };
    case 'proposal':
      return second ? { key: 'proposals', page: <ProposalPage key={second} proposalId={second} /> } : { key: '', page: <NotFoundPage /> };
    case 'daos':
      return { key: 'daos', page: <DaosPage /> };
    case 'dao':
      return second ? { key: 'daos', page: <DaoPage key={second} spaceId={second} /> } : { key: 'daos', page: <DaosPage /> };
    case 'people':
    case 'identities':
      return { key: 'people', page: <PeoplePage /> };
    case 'person':
    case 'identity':
      return second ? { key: 'people', page: <PersonPage key={second} username={second} /> } : { key: 'people', page: <PeoplePage /> };
    case 'insights':
      return { key: '', page: <InsightsPage /> };
    case 'data':
      return { key: '', page: <DataPage /> };
    case 'methodology':
      return { key: '', page: <MethodologyPage /> };
    default:
      return { key: '', page: <NotFoundPage /> };
  }
}

const Shell: React.FC = () => {
  const route = useRoute();
  const { open: openAnalyst } = useAnalyst();
  const { reload: reloadDaos } = useDaos();
  const [searchOpen, setSearchOpen] = useState(false);
  const { key, page } = resolve(route);

  // New page: start at the top (switching a tab inside a page keeps the scroll position).
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [route.path]);

  // Ctrl/Cmd+K toggles search.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearchOpen((o) => !o);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // When the backend comes back after an outage, refetch what failed while it was down.
  const onRecovered = useCallback(() => {
    clearCatalogueCache();
    clearSyncStatusCache();
    reloadDaos();
  }, [reloadDaos]);

  return (
    <div className="min-h-screen bg-[#FAF8F5] text-[#181715] flex flex-col font-sans selection:bg-[#EBE5DA]">
      <a href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus(); }} className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:px-3 focus:py-2 focus:bg-white focus:rounded">
        Skip to content
      </a>
      <TopNav activeKey={key} onOpenSearch={() => setSearchOpen(true)} onOpenAnalyst={() => openAnalyst()} />
      <ConnectionBanner onRecovered={onRecovered} />
      <main id="main" tabIndex={-1} className="flex-1 w-full pb-16 outline-none">
        {page}
      </main>
      <footer className="border-t border-[#E8E2D8] py-6 text-xs text-[#7D776E]">
        <div className="quorum-container flex flex-wrap justify-between gap-x-6 gap-y-3">
          <span>Quorum · read-only governance analytics from Snapshot and public DAO forums. Not financial or voting advice.</span>
          <nav aria-label="About the data" className="flex flex-wrap gap-4">
            <Link to="/methodology" className="hover:text-[#181715] hover:underline">How it works</Link>
            <Link to="/data" className="hover:text-[#181715] hover:underline">Data coverage</Link>
            <Link to="/insights" className="hover:text-[#181715] hover:underline">Cross-DAO research</Link>
          </nav>
        </div>
      </footer>
      <AnalystPanel />
      <SearchModal isOpen={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  );
};

export const App: React.FC = () => (
  <DaosProvider>
    <AnalystProvider>
      <Shell />
    </AnalystProvider>
  </DaosProvider>
);

export default App;
