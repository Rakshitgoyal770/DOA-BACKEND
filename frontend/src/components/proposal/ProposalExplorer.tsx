import React, { useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import type { DaoSummary, ProposalSummary } from '../../api/types';
import { daoMeta } from '../../lib/daoMeta';
import { DEFAULT_FILTERS, SORTS, countByStatus, filterProposals, type ExplorerFilters, type SortKey } from '../../lib/proposals';
import type { DisplayStatus } from '../../lib/status';
import { Select, TextInput } from '../ui/Field';
import { Pagination } from '../ui/Pagination';
import { Button } from '../ui/Button';
import { EmptyState } from '../ui/States';
import { ProposalRow } from './ProposalRow';

const PAGE_SIZE = 15;

const STATUS_TABS: { key: DisplayStatus | 'all'; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Open now' },
  { key: 'pending', label: 'Upcoming' },
  { key: 'ended', label: 'Ended, result not synced' },
  { key: 'closed', label: 'Closed' },
];

interface ProposalExplorerProps {
  proposals: ProposalSummary[];
  daos: DaoSummary[] | null;
  /** When set, the list is locked to one DAO and the DAO chips are hidden. */
  lockedDao?: string;
  value: ExplorerFilters;
  onChange: (next: ExplorerFilters) => void;
}

/** Search, DAO chips, status tabs and sort over the proposal catalogue (all filtering is local). */
export const ProposalExplorer: React.FC<ProposalExplorerProps> = ({ proposals, daos, lockedDao, value, onChange }) => {
  const nameOf = useMemo(() => new Map((daos ?? []).map((d) => [d.id, d.name])), [daos]);
  const scoped = useMemo(() => (lockedDao ? proposals.filter((p) => p.space_id === lockedDao) : proposals), [proposals, lockedDao]);
  const dao = lockedDao ?? value.dao;
  const inDao = useMemo(() => (dao ? scoped.filter((p) => p.space_id === dao) : scoped), [scoped, dao]);
  const statusCounts = useMemo(() => countByStatus(inDao), [inDao]);
  const daoCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of proposals) m.set(p.space_id, (m.get(p.space_id) ?? 0) + 1);
    return m;
  }, [proposals]);

  // The search box is typed into locally and pushed up after a pause, so the URL isn't rewritten per keystroke.
  const [draft, setDraft] = useState(value.q);
  useEffect(() => {
    setDraft(value.q);
  }, [value.q]);
  useEffect(() => {
    if (draft === value.q) return;
    const t = setTimeout(() => onChange({ ...value, q: draft, page: 0 }), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  const results = useMemo(
    () => filterProposals(scoped, { q: value.q, dao, status: value.status, sort: value.sort }),
    [scoped, value.q, dao, value.status, value.sort],
  );

  const pageCount = Math.max(1, Math.ceil(results.length / PAGE_SIZE));
  const page = Math.min(value.page, pageCount - 1);
  const visible = results.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const isFiltered = !!(value.q || value.status !== 'all' || (!lockedDao && value.dao));

  const set = (patch: Partial<ExplorerFilters>) => onChange({ ...value, page: 0, ...patch });

  return (
    <div className="space-y-5">
      {!lockedDao && daos && daos.length > 1 && (
        <div role="group" aria-label="Filter by DAO" className="flex flex-wrap gap-2">
          <Chip active={!value.dao} onClick={() => set({ dao: '' })}>
            All DAOs <span className="font-mono opacity-70">{proposals.length}</span>
          </Chip>
          {daos.map((d) => (
            <Chip key={d.id} active={value.dao === d.id} onClick={() => set({ dao: value.dao === d.id ? '' : d.id })}>
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: daoMeta(d.id, d.name).color }} aria-hidden />
              {d.name} <span className="font-mono opacity-70">{daoCounts.get(d.id) ?? 0}</span>
            </Chip>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#E8E2D8]">
        <div role="tablist" aria-label="Filter by status" className="flex gap-1 overflow-x-auto -mb-px">
          {STATUS_TABS.filter((t) => t.key === 'all' || statusCounts[t.key] > 0 || value.status === t.key).map((t) => {
            const n = t.key === 'all' ? inDao.length : statusCounts[t.key];
            const active = value.status === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => set({ status: t.key })}
                className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 transition-colors cursor-pointer ${
                  active ? 'border-[#181715] text-[#181715] font-semibold' : 'border-transparent text-[#5C5852] hover:text-[#181715]'
                }`}
              >
                {t.label} <span className="font-mono text-[11px] text-[#8C867D]">{n}</span>
              </button>
            );
          })}
        </div>
        <form role="search" onSubmit={(e) => e.preventDefault()} className="flex flex-wrap items-center gap-2 pb-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8C867D] pointer-events-none" aria-hidden />
            <TextInput
              type="search"
              aria-label="Search proposal titles"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Search titles"
              className="w-56 pl-9"
            />
          </div>
          <Select aria-label="Sort proposals" value={value.sort} onChange={(e) => set({ sort: e.target.value as SortKey })}>
            {SORTS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </Select>
        </form>
      </div>

      <div className="flex items-center justify-between text-xs text-[#5C5852]" aria-live="polite">
        <span>
          {results.length} proposal{results.length === 1 ? '' : 's'}
          {isFiltered && ` of ${scoped.length}`}
        </span>
        {isFiltered && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setDraft('');
              onChange({ ...DEFAULT_FILTERS, sort: value.sort });
            }}
          >
            Clear filters
          </Button>
        )}
      </div>

      {visible.length === 0 ? (
        <EmptyState
          title={scoped.length === 0 ? 'No proposals stored yet' : 'No proposals match these filters'}
          description={
            scoped.length === 0 ? 'The database has no proposals for this selection. They appear after a data sync.' : 'Try a different search term or clear the filters.'
          }
        />
      ) : (
        <ul className="space-y-3">
          {visible.map((p) => (
            <li key={p.id}>
              <ProposalRow proposal={p} daoName={nameOf.get(p.space_id) ?? p.space_id} showDao={!lockedDao} />
            </li>
          ))}
        </ul>
      )}

      <Pagination page={page} pageSize={PAGE_SIZE} total={results.length} onChange={(p) => onChange({ ...value, page: p })} />
    </div>
  );
};

const Chip: React.FC<{ active: boolean; onClick: () => void; children: React.ReactNode }> = ({ active, onClick, children }) => (
  <button
    type="button"
    aria-pressed={active}
    onClick={onClick}
    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors cursor-pointer ${
      active ? 'bg-[#181715] text-[#FAF8F5] border-[#181715]' : 'bg-white text-[#4A463F] border-[#DDD5C7] hover:border-[#181715]'
    }`}
  >
    {children}
  </button>
);
