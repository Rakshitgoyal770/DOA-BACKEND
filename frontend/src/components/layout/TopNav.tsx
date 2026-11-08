import React, { useState } from 'react';
import { Menu, MessageSquareText, Search, X } from 'lucide-react';
import { Link } from '../ui/Link';

interface NavItem {
  key: string;
  label: string;
  to: string;
}

/** Three places people go: proposals (the product), DAOs (a way in), people (who votes and says what). */
const NAV_ITEMS: NavItem[] = [
  { key: 'proposals', label: 'Proposals', to: '/' },
  { key: 'daos', label: 'DAOs', to: '/daos' },
  { key: 'people', label: 'People', to: '/people' },
];

interface TopNavProps {
  activeKey: string;
  onOpenSearch: () => void;
  onOpenAnalyst: () => void;
}

export const TopNav: React.FC<TopNavProps> = ({ activeKey, onOpenSearch, onOpenAnalyst }) => {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 w-full bg-[#FAF8F5]/95 backdrop-blur-md border-b border-[#E8E2D8]">
      <div className="quorum-container h-16 flex items-center justify-between gap-4">
        <div className="flex items-center gap-8 lg:gap-12">
          <Link to="/" className="font-serif text-2xl font-bold tracking-tight text-[#181715] shrink-0" aria-label="QUORUM home">
            QUORUM
          </Link>

          <nav aria-label="Primary" className="hidden md:flex items-center gap-6 lg:gap-7 text-sm">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.key}
                to={item.to}
                aria-current={activeKey === item.key ? 'page' : undefined}
                className={`transition-colors py-1 font-medium ${activeKey === item.key ? 'text-[#181715] font-semibold' : 'text-[#5C5852] hover:text-[#181715]'}`}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          <button
            onClick={onOpenSearch}
            className="hidden sm:flex items-center gap-2 pl-3.5 pr-2.5 h-9 w-56 lg:w-64 bg-white border border-[#DDD5C7] hover:border-[#181715] rounded-full text-xs text-[#8C867D] transition-colors cursor-pointer shadow-xs"
            aria-label="Search (Ctrl+K)"
          >
            <Search size={14} aria-hidden />
            <span className="flex-1 text-left truncate">Search proposals, DAOs, people…</span>
            <kbd className="px-1.5 py-0.5 bg-[#F0ECE3] rounded text-[10px] font-mono text-[#7D776E]">Ctrl K</kbd>
          </button>
          <button onClick={onOpenSearch} className="sm:hidden p-2 rounded-lg text-[#5C5852] hover:text-[#181715] cursor-pointer" aria-label="Search">
            <Search size={18} />
          </button>

          <button
            onClick={onOpenAnalyst}
            className="px-4 h-9 rounded-full bg-[#181715] hover:bg-[#282623] text-[#FAF8F5] text-xs font-medium transition-colors cursor-pointer whitespace-nowrap flex items-center gap-2"
          >
            <MessageSquareText size={14} aria-hidden />
            <span>Ask</span>
          </button>

          <button
            onClick={() => setMenuOpen((o) => !o)}
            className="md:hidden p-2 rounded-lg text-[#5C5852] hover:text-[#181715] cursor-pointer"
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={menuOpen}
            aria-controls="mobile-menu"
          >
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>

      {menuOpen && (
        <nav id="mobile-menu" aria-label="Primary mobile" className="md:hidden border-t border-[#E8E2D8] bg-[#FAF8F5]">
          <ul className="quorum-container py-2">
            {NAV_ITEMS.map((item) => (
              <li key={item.key}>
                <Link
                  to={item.to}
                  onClick={() => setMenuOpen(false)}
                  aria-current={activeKey === item.key ? 'page' : undefined}
                  className={`block py-3 text-sm border-b border-[#F0ECE3] ${activeKey === item.key ? 'font-semibold text-[#181715]' : 'text-[#5C5852]'}`}
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  );
};
