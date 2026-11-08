import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Building2, FileText, Search, User, Wallet } from 'lucide-react';
import { getProposalCatalogue } from '../../api/catalogue';
import { api } from '../../api/endpoints';
import { useDaos } from '../../context/DaosContext';
import { useAsync } from '../../hooks/useAsync';
import { useDebounced } from '../../hooks/useDebounced';
import { navigate } from '../../hooks/useRouter';
import { daoMeta } from '../../lib/daoMeta';
import { isWalletAddress, truncateAddress } from '../../lib/format';
import { filterProposals } from '../../lib/proposals';
import { deriveStatus, STATUS_LABEL } from '../../lib/status';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface Item {
  key: string;
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  to: string;
}

/**
 * Ctrl/Cmd+K search. Proposals and DAOs are matched locally (the API has no
 * proposal search); people are searched server-side via GET /identities?q=.
 */
export const SearchModal: React.FC<SearchModalProps> = ({ isOpen, onClose }) =>
  isOpen ? <SearchDialog onClose={onClose} /> : null; // mounted only while open, so its state starts fresh each time

const SearchDialog: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const { daos, nameOf } = useDaos();
  const debounced = useDebounced(query.trim(), 300);

  const catalogue = useAsync(() => getProposalCatalogue(), []);
  const people = useAsync(
    (signal) => api.listIdentities({ q: debounced, limit: 5 }, { signal }),
    [debounced],
    { enabled: debounced.length >= 2 },
  );

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const q = query.trim().toLowerCase();

  const items = useMemo<Item[]>(() => {
    if (q.length < 2) return [];
    const out: Item[] = [];
    (daos ?? [])
      .filter((d) => d.name.toLowerCase().includes(q) || d.id.toLowerCase().includes(q))
      .forEach((d) =>
        out.push({ key: `dao-${d.id}`, icon: <Building2 size={15} />, title: d.name, subtitle: `DAO · ${daoMeta(d.id, d.name).symbol}`, to: `/dao/${encodeURIComponent(d.id)}` }),
      );
    filterProposals(catalogue.data ?? [], { q, dao: '', status: 'all', sort: 'votes' })
      .slice(0, 6)
      .forEach((p) =>
        out.push({
          key: `p-${p.id}`,
          icon: <FileText size={15} />,
          title: p.title,
          subtitle: `${nameOf(p.space_id)} · ${STATUS_LABEL[deriveStatus(p)]}`,
          to: `/proposal/${encodeURIComponent(p.id)}`,
        }),
      );
    if (isWalletAddress(query)) {
      out.push({
        key: 'wallet',
        icon: <Wallet size={15} />,
        title: `Look up wallet ${truncateAddress(query.trim(), 5)}`,
        subtitle: 'Search linked forum identities',
        to: `/people?q=${encodeURIComponent(query.trim())}`,
      });
    }
    // Only show results that belong to the current text (stale people results would otherwise flash).
    if (people.data && debounced === query.trim()) {
      people.data.items.forEach((i) =>
        out.push({
          key: `u-${i.forum_username}`,
          icon: <User size={15} />,
          title: i.ens_name ? `${i.forum_username} (${i.ens_name})` : i.forum_username,
          subtitle: `Forum user · ${truncateAddress(i.wallet_address, 5)}`,
          to: `/person/${encodeURIComponent(i.forum_username)}`,
        }),
      );
    }
    return out;
  }, [q, query, debounced, daos, catalogue.data, people.data, nameOf]);

  const activeIndex = Math.min(active, items.length - 1);

  const go = (item: Item) => {
    navigate(item.to);
    onClose();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
    else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((a) => Math.min(items.length - 1, a + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === 'Enter' && items[activeIndex]) {
      e.preventDefault();
      go(items[activeIndex]);
    }
  };

  const searching = q.length >= 2 && (catalogue.loading || people.loading);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4 bg-[#181715]/40 backdrop-blur-[2px]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label="Search" className="w-full max-w-xl bg-white border border-[#DDD5C7] rounded-xl shadow-modal overflow-hidden" onKeyDown={onKeyDown}>
        <div className="flex items-center gap-3 px-4 border-b border-[#E8E2D8]">
          <Search size={16} className="text-[#8C867D]" aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            placeholder="Search proposals, DAOs, forum users, wallets…"
            aria-label="Search"
            role="combobox"
            aria-expanded={items.length > 0}
            aria-controls="search-results"
            aria-activedescendant={items[activeIndex] ? `search-${items[activeIndex].key}` : undefined}
            className="flex-1 h-12 bg-transparent text-sm placeholder:text-[#8C867D] focus:outline-none"
          />
          <kbd className="px-1.5 py-0.5 bg-[#F0ECE3] rounded text-[10px] font-mono text-[#7D776E]">Esc</kbd>
        </div>

        <ul id="search-results" role="listbox" className="max-h-[50vh] overflow-y-auto py-1">
          {items.map((item, i) => (
            <li key={item.key} id={`search-${item.key}`} role="option" aria-selected={i === activeIndex}>
              <button
                type="button"
                onMouseEnter={() => setActive(i)}
                onClick={() => go(item)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left cursor-pointer ${i === activeIndex ? 'bg-[#F4F0E8]' : ''}`}
              >
                <span className="text-[#8C867D] shrink-0">{item.icon}</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-[#181715] truncate">{item.title}</span>
                  {item.subtitle && <span className="block text-[11px] text-[#7D776E] truncate">{item.subtitle}</span>}
                </span>
              </button>
            </li>
          ))}
        </ul>

        <div className="px-4 py-2.5 border-t border-[#F0ECE3] text-xs text-[#7D776E]" aria-live="polite">
          {q.length < 2
            ? 'Type at least 2 characters.'
            : catalogue.error
              ? 'Could not load proposals. Check the connection.'
              : searching && items.length === 0
                ? 'Searching…'
                : items.length === 0
                  ? 'No results.'
                  : `${items.length} result${items.length === 1 ? '' : 's'}`}
        </div>
      </div>
    </div>
  );
};
