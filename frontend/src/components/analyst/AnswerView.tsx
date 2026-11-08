import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Database, FileText, Info } from 'lucide-react';
import { getProposalCatalogue } from '../../api/catalogue';
import type { ChatLookup, ChatResponse, ChatSource } from '../../api/types';
import { useAsync } from '../../hooks/useAsync';
import { parseAnswer, type Inline } from '../../lib/answer';
import { formatCompact, truncateAddress } from '../../lib/format';
import { ConfidenceBadge } from '../ui/Badge';
import { Link } from '../ui/Link';

/** Renders one analyst answer with its evidence. `turnId` namespaces element ids so several answers can coexist. */
export const AnswerView: React.FC<{ response: ChatResponse; turnId: string }> = ({ response, turnId }) => {
  const blocks = parseAnswer(response.answer);
  const [openSource, setOpenSource] = useState<number | null>(null);
  // Sources from a search across all proposals mix proposals: name the proposal on each one (catalogue is cached).
  const catalogue = useAsync(() => getProposalCatalogue(), []);
  const titleOf = useMemo(() => new Map((catalogue.data ?? []).map((p) => [p.id, p.title])), [catalogue.data]);

  const jumpToSource = (n: number) => {
    setOpenSource(n);
    requestAnimationFrame(() => document.getElementById(`${turnId}-source-${n}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
  };

  const renderInline = (parts: Inline[]) =>
    parts.map((part, i) => {
      switch (part.type) {
        case 'text':
          return <React.Fragment key={i}>{part.text}</React.Fragment>;
        case 'bold':
          return <strong key={i}>{part.text}</strong>;
        case 'facts':
          return (
            <span key={i} className="mx-0.5 inline-flex items-center gap-0.5 rounded bg-[#EEF1F8] border border-[#CCD6ED] px-1 text-[10px] font-semibold uppercase text-[#243260] align-baseline" title="From a database lookup (see “What the analyst looked up”)">
              <Database size={9} aria-hidden /> Facts
            </span>
          );
        case 'background':
          return (
            <span key={i} className="mx-0.5 inline-flex items-center gap-0.5 rounded bg-[#FEF6EA] border border-[#F5DCB5] px-1 text-[10px] font-semibold uppercase text-[#8C5814] align-baseline" title="General knowledge. Not from our database.">
              <Info size={9} aria-hidden /> Background
            </span>
          );
        case 'cite':
          return (
            <span key={i} className="mx-0.5">
              {part.numbers.map((n) => {
                const exists = n >= 1 && n <= response.sources.length;
                return exists ? (
                  <button
                    key={n}
                    type="button"
                    onClick={() => jumpToSource(n)}
                    className="mx-px inline-flex items-center rounded bg-[#F0ECE3] hover:bg-[#EBE5DA] border border-[#DDD5C7] px-1 text-[10px] font-mono font-semibold text-[#181715] cursor-pointer align-baseline"
                    aria-label={`Show source ${n}`}
                  >
                    {n}
                  </button>
                ) : (
                  <span key={n} className="mx-px rounded border border-dashed border-[#DDD5C7] px-1 text-[10px] font-mono text-[#8C867D]" title="This source was not returned with the answer">
                    {n}
                  </span>
                );
              })}
            </span>
          );
      }
    });

  return (
    <div className="space-y-4">
      <div className="space-y-3 text-sm leading-relaxed text-[#181715]">
        {blocks.map((b, i) =>
          b.type === 'p' ? (
            <p key={i}>{renderInline(b.content)}</p>
          ) : b.type === 'ul' ? (
            <ul key={i} className="list-disc pl-5 space-y-1.5">
              {b.items.map((item, j) => (
                <li key={j}>{renderInline(item)}</li>
              ))}
            </ul>
          ) : (
            <ol key={i} className="list-decimal pl-5 space-y-1.5">
              {b.items.map((item, j) => (
                <li key={j}>{renderInline(item)}</li>
              ))}
            </ol>
          ),
        )}
      </div>

      <div className="text-[11px] text-[#7D776E] flex flex-wrap gap-x-3 gap-y-1">
        <span>
          Answered by <span className="font-mono">{response.provider}</span>
        </span>
        <span>
          {response.chunks_found} passage{response.chunks_found === 1 ? '' : 's'} retrieved
        </span>
      </div>

      {response.sources.length > 0 && (
        <section aria-label="Sources">
          <div className="editorial-label text-[10px] mb-2 flex items-center gap-1.5">
            <FileText size={11} aria-hidden /> Sources
          </div>
          <ol className="space-y-1.5">
            {response.sources.map((s, i) => (
              <SourceItem key={s.id} source={s} proposalTitle={s.proposal_id ? titleOf.get(s.proposal_id) : undefined} n={i + 1} id={`${turnId}-source-${i + 1}`} open={openSource === i + 1} onToggle={() => setOpenSource(openSource === i + 1 ? null : i + 1)} />
            ))}
          </ol>
        </section>
      )}

      {response.lookups.length > 0 && (
        <section aria-label="Lookups">
          <div className="editorial-label text-[10px] mb-2 flex items-center gap-1.5">
            <Database size={11} aria-hidden /> What the analyst looked up
          </div>
          <ul className="space-y-1.5">
            {response.lookups.map((l, i) => (
              <LookupItem key={i} lookup={l} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
};

const SourceItem: React.FC<{ source: ChatSource; proposalTitle?: string; n: number; id: string; open: boolean; onToggle: () => void }> = ({
  source: s,
  proposalTitle,
  n,
  id,
  open,
  onToggle,
}) => {
  const label =
    s.source_type === 'proposal_body' ? 'Proposal text' : s.author ? `Forum post by ${s.author}` : 'Forum post';
  return (
    <li id={id} className="border border-[#E8E2D8] rounded-lg bg-white">
      <button type="button" onClick={onToggle} aria-expanded={open} className="w-full flex items-center gap-2 p-2.5 text-left cursor-pointer">
        {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
        <span className="rounded bg-[#F0ECE3] border border-[#DDD5C7] px-1 text-[10px] font-mono font-semibold">{n}</span>
        <span className="flex-1 min-w-0">
          <span className="block text-xs font-medium truncate">{label}</span>
          {proposalTitle && <span className="block text-[11px] text-[#7D776E] truncate">on {proposalTitle}</span>}
        </span>
        {s.link_confidence && <ConfidenceBadge level={s.link_confidence} />}
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 text-xs">
          <blockquote className="border-l-2 border-[#DDD5C7] pl-3 text-[#4A463F] whitespace-pre-wrap break-words max-h-48 overflow-y-auto">{s.document}</blockquote>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-[#5C5852]">
            {s.wallet && (
              <div className="col-span-2">
                <dt className="inline editorial-label text-[9px] mr-1.5">Wallet</dt>
                <dd className="inline font-mono" title={s.wallet}>{s.ens_name ?? truncateAddress(s.wallet, 5)}</dd>
              </div>
            )}
            {s.voting_power !== null && s.voting_power !== undefined && (
              <div>
                <dt className="inline editorial-label text-[9px] mr-1.5">Voting power</dt>
                <dd className="inline font-mono">{formatCompact(s.voting_power)}</dd>
              </div>
            )}
            {s.voted && (
              <div>
                <dt className="inline editorial-label text-[9px] mr-1.5">Voted</dt>
                <dd className="inline">{s.voted}</dd>
              </div>
            )}
            <div>
              <dt className="inline editorial-label text-[9px] mr-1.5" title="How far the passage is from the question in meaning: lower is closer.">Match distance</dt>
              <dd className="inline font-mono">{s.distance}</dd>
            </div>
          </dl>
          {s.proposal_id && (
            <Link to={`/proposal/${encodeURIComponent(s.proposal_id)}`} className="inline-block underline underline-offset-2 font-medium">
              Open proposal
            </Link>
          )}
        </div>
      )}
    </li>
  );
};

const LookupItem: React.FC<{ lookup: ChatLookup }> = ({ lookup }) => {
  const [open, setOpen] = useState(false);
  const args = Object.entries(lookup.arguments ?? {})
    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(', ');
  return (
    <li className="border border-[#E8E2D8] rounded-lg bg-white">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="w-full flex items-center gap-2 p-2.5 text-left cursor-pointer">
        {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
        <span className="font-mono text-[11px] font-semibold">{lookup.tool}</span>
        <span className="font-mono text-[10px] text-[#7D776E] flex-1 min-w-0 truncate">{args}</span>
        {lookup.automatic && <span className="editorial-label text-[8px]">auto</span>}
      </button>
      {open && (
        <pre className="mx-3 mb-3 p-2 rounded bg-[#F4F0E8] text-[10px] leading-snug font-mono overflow-auto max-h-56 whitespace-pre-wrap break-words">
          {JSON.stringify(lookup.result, null, 2)}
        </pre>
      )}
    </li>
  );
};
