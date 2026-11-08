import React, { useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import { api } from '../api/endpoints';
import { ConfidenceBadge } from '../components/ui/Badge';
import { Select, TextInput } from '../components/ui/Field';
import { Link } from '../components/ui/Link';
import { Pagination } from '../components/ui/Pagination';
import { EmptyState, ErrorState, LoadingBlock } from '../components/ui/States';
import { useAsync } from '../hooks/useAsync';
import { useDebounced } from '../hooks/useDebounced';
import { href, navigate, useRoute } from '../hooks/useRouter';
import { formatInt, truncateAddress } from '../lib/format';

const PAGE_SIZE = 25;
const CONFIDENCES = ['medium', 'high', 'certain'] as const;

/**
 * People who both discuss and vote: forum users we could match to a voting wallet
 * (GET /identities). Each opens a page with their votes next to what they wrote.
 */
export const PeoplePage: React.FC = () => {
  const route = useRoute();
  const q = route.query.get('q') ?? '';
  const conf = route.query.get('conf') ?? '';
  const page = Math.max(0, Number(route.query.get('page')) || 0);

  const [draft, setDraft] = useState(q);
  useEffect(() => {
    setDraft(q);
  }, [q]);
  const debounced = useDebounced(draft.trim(), 300);
  const update = (patch: Record<string, string | number | null>) => navigate(href('/people', { q, conf, page: page || null, ...patch }), { replace: true });
  useEffect(() => {
    if (debounced !== q) update({ q: debounced, page: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debounced]);

  const stats = useAsync((signal) => api.identityStats({ signal }), []);
  const list = useAsync(
    (signal) => api.listIdentities({ q: q || undefined, min_confidence: conf || undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE }, { signal }),
    [q, conf, page],
    { keepPrevious: true },
  );

  return (
    <div className="quorum-container py-8 sm:py-10 space-y-6 animate-fade-in">
      <header className="max-w-3xl">
        <h1 className="editorial-headline text-3xl sm:text-4xl text-[#181715]">People</h1>
        <p className="text-sm text-[#4A463F] mt-2 leading-relaxed">
          Forum members we could match to the wallet they vote with, so you can see what someone argued next to how they voted.
          {stats.data && (
            <span className="text-[#5C5852]">
              {' '}
              {formatInt(stats.data.resolved)} of {formatInt(stats.data.forum_users)} forum users are matched so far; each match says how sure it is.
            </span>
          )}
        </p>
      </header>

      <form role="search" onSubmit={(e) => e.preventDefault()} className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8C867D] pointer-events-none" aria-hidden />
          <TextInput type="search" aria-label="Search people" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Username, ENS name or wallet" className="w-full pl-9" />
        </div>
        <Select aria-label="Minimum match confidence" value={conf} onChange={(e) => update({ conf: e.target.value, page: null })}>
          <option value="">Any match</option>
          {CONFIDENCES.map((c) => (
            <option key={c} value={c}>
              {c} or better
            </option>
          ))}
        </Select>
      </form>

      {list.error ? (
        <ErrorState error={list.error} onRetry={list.reload} />
      ) : !list.data ? (
        <LoadingBlock label="Loading people" rows={6} />
      ) : list.data.items.length === 0 ? (
        <EmptyState title="Nobody matches" description="Try a shorter search or allow any match." />
      ) : (
        <div className={list.loading ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
          <p className="text-xs text-[#5C5852] mb-2" aria-live="polite">
            {formatInt(list.data.total)} {list.data.total === 1 ? 'person' : 'people'}
          </p>
          <ul className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {list.data.items.map((i) => (
              <li key={i.forum_username}>
                <Link
                  to={`/person/${encodeURIComponent(i.forum_username)}`}
                  className="group flex items-start justify-between gap-3 p-4 h-full bg-white border border-[#E8E2D8] rounded-xl hover:border-[#181715] transition-colors"
                >
                  <div className="min-w-0">
                    <div className="font-semibold text-sm text-[#181715] group-hover:underline truncate">@{i.forum_username}</div>
                    <div className="text-xs text-[#5C5852] truncate" title={i.wallet_address}>
                      {i.ens_name ?? <span className="font-mono">{truncateAddress(i.wallet_address, 5)}</span>}
                    </div>
                    <div className="text-xs text-[#7D776E] mt-1">{formatInt(i.post_count)} forum posts</div>
                  </div>
                  <ConfidenceBadge level={i.confidence_level} />
                </Link>
              </li>
            ))}
          </ul>
          <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onChange={(p) => update({ page: p || null })} />
        </div>
      )}
    </div>
  );
};
