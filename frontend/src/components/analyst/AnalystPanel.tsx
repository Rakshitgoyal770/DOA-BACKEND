import React, { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Send, Sparkles, Square, Trash2, X } from 'lucide-react';
import { api } from '../../api/endpoints';
import { getSyncStatus, lastSyncActivity } from '../../api/freshness';
import { ApiError, errorMessage, isAbortError } from '../../api/client';
import type { ChatResponse } from '../../api/types';
import { useAnalyst } from '../../context/AnalystContext';
import { useDaos } from '../../context/DaosContext';
import { useAsync } from '../../hooks/useAsync';
import { formatDate } from '../../lib/format';
import { PROMPTS, availableLevels, buildChatRequest, daoPrefix, levelLabel, scopeKey, type Level } from '../../lib/analystScope';
import { Button } from '../ui/Button';
import { AnswerView } from './AnswerView';

interface Turn {
  id: string;
  query: string;
  /** label of the level it was asked at, e.g. "This proposal", "Arbitrum DAO", "All DAOs" */
  scopeLabel: string;
  state: 'loading' | 'done' | 'error';
  response?: ChatResponse;
  error?: string;
}

const MIN_LEN = 3; // backend: ChatRequest.query min_length
const MAX_LEN = 2000; // backend: ChatRequest.query max_length

let turnCounter = 0;

/** ["A", "B", "C"] -> "A, B and C" */
function listNames(names: string[]): string {
  return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
}

/**
 * Right-hand drawer for asking questions (POST /chat). Conversation lives in this
 * component, which stays mounted, so closing and re-opening keeps the history.
 */
export const AnalystPanel: React.FC = () => {
  const { isOpen, scope, close } = useAnalyst();
  const { daos } = useDaos();
  // Answers say "as of our latest data"; this tells the reader which date that is. Fetched when opened (cached).
  const sync = useAsync(() => getSyncStatus(), [], { enabled: isOpen });
  const asOf = lastSyncActivity(sync.data);
  const daoNames = daos?.length ? listNames(daos.map((d) => d.name)) : 'the DAOs we track';
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  // The user's level choice is remembered per scope, so opening the analyst from another page picks that page's most specific level again.
  const [choice, setChoice] = useState<{ key: string; level: Level } | null>(null);
  const levels = availableLevels(scope);
  const level: Level = choice && choice.key === scopeKey(scope) && levels.includes(choice.level) ? choice.level : levels[0];
  // The DAO level adds a prefix to the question, which counts toward the backend's length limit.
  const maxInput = MAX_LEN - (level === 'dao' && scope?.dao ? daoPrefix(scope.dao.name).length : 0);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const busy = turns.some((t) => t.state === 'loading');
  const trimmed = input.trim();
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_LEN;
  const canSend = !busy && trimmed.length >= MIN_LEN && trimmed.length <= maxInput;

  useEffect(() => {
    if (!isOpen) return;
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, close]);

  useEffect(() => {
    // braces matter: some browsers return a Promise from scrollIntoView, and an effect must not return one
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const ask = async (query: string) => {
      const q = query.trim();
      // abortRef is set synchronously, so unlike `busy` it also stops a fast double-click.
      if (busy || abortRef.current || q.length < MIN_LEN || q.length > maxInput) return;
      const request = buildChatRequest(level, scope, q);
      const scopeLabel = levelLabel(level, scope);
      const id = `t${++turnCounter}`;
      const controller = new AbortController();
      abortRef.current = controller;
      setTurns((t) => [...t, { id, query: q, scopeLabel, state: 'loading' }]);
      setInput('');
      try {
        const response = await api.chat(request, { signal: controller.signal });
        setTurns((t) => t.map((x) => (x.id === id ? { ...x, state: 'done', response } : x)));
      } catch (err) {
        if (isAbortError(err)) {
          setTurns((t) => t.map((x) => (x.id === id ? { ...x, state: 'error', error: 'Cancelled.' } : x)));
          return;
        }
        let message = errorMessage(err);
        if (err instanceof ApiError && err.status !== null && err.status >= 500) {
          message = 'The analyst could not answer: every language-model provider failed or is rate-limited. Please try again in a minute.';
        }
        setTurns((t) => t.map((x) => (x.id === id ? { ...x, state: 'error', error: message } : x)));
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }
  };

  if (!isOpen) return null;

  const prompts = PROMPTS[level];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-[#181715]/30 backdrop-blur-[1px]" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <aside role="dialog" aria-modal="true" aria-label="Governance analyst" className="w-full sm:max-w-xl h-full bg-[#FAF8F5] border-l border-[#DDD5C7] shadow-modal flex flex-col animate-fade-in">
        <header className="flex items-start justify-between gap-3 p-5 border-b border-[#E8E2D8] bg-[#FFFDF9]">
          <div>
            <div className="flex items-center gap-2 font-serif text-xl text-[#181715]">
              <Sparkles size={17} aria-hidden /> Governance analyst
            </div>
            <p className="text-xs text-[#5C5852] mt-1">
              Answers are written by a language model from our governance database. Check the sources.
              {asOf && <> Data last synced <strong>{formatDate(new Date(asOf).getTime() / 1000)}</strong>: a vote still open then may have ended since.</>}
            </p>
          </div>
          <div className="flex items-center gap-1">
            {turns.length > 0 && (
              <Button size="sm" variant="ghost" disabled={busy} icon={<Trash2 size={13} />} onClick={() => setTurns([])} aria-label="Clear conversation">
                Clear
              </Button>
            )}
            <button onClick={close} aria-label="Close analyst" className="p-1.5 rounded text-[#8C867D] hover:text-[#181715] hover:bg-[#F4F0E8] cursor-pointer">
              <X size={18} />
            </button>
          </div>
        </header>

        {levels.length > 1 && (
          <div className="px-5 py-3 border-b border-[#E8E2D8] bg-white space-y-2">
            <div role="radiogroup" aria-label="What to ask about" className="flex flex-wrap gap-1.5">
              {levels.map((l) => (
                <button
                  key={l}
                  type="button"
                  role="radio"
                  aria-checked={l === level}
                  onClick={() => setChoice({ key: scopeKey(scope), level: l })}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors cursor-pointer max-w-full truncate ${
                    l === level ? 'bg-[#181715] text-[#FAF8F5] border-[#181715]' : 'bg-white text-[#4A463F] border-[#DDD5C7] hover:border-[#181715]'
                  }`}
                >
                  {levelLabel(l, scope)}
                </button>
              ))}
            </div>
            {level === 'proposal' && scope?.proposal && <p className="text-[11px] text-[#7D776E] truncate">Focused on: {scope.proposal.title}</p>}
            {level === 'dao' && <p className="text-[11px] text-[#7D776E]">Questions are limited to this DAO&apos;s proposals.</p>}
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-5 space-y-6" aria-live="polite">
          {turns.length === 0 && (
            <div className="space-y-3">
              <p className="text-sm text-[#4A463F]">
                Ask about proposals, who voted how, and what people argued on the forums, for {daoNames}.
              </p>
              <div className="flex flex-col gap-2">
                {prompts.map((p) => (
                  <button key={p} disabled={busy} onClick={() => void ask(p)} className="text-left text-sm px-3 py-2 rounded-lg border border-[#DDD5C7] bg-white hover:border-[#181715] transition-colors cursor-pointer disabled:opacity-50">
                    {p}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t) => (
            <div key={t.id} className="space-y-3">
              <div className="flex flex-col items-end gap-1">
                <span className="editorial-label text-[9px]">{t.scopeLabel}</span>
                <div className="max-w-[90%] rounded-2xl rounded-tr-sm bg-[#181715] text-[#FAF8F5] px-4 py-2.5 text-sm break-words">{t.query}</div>
              </div>
              <div className="rounded-xl border border-[#E8E2D8] bg-[#FFFDF9] p-4">
                {t.state === 'loading' && (
                  <div role="status" className="flex items-center gap-3 text-sm text-[#5C5852]">
                    <span className="w-4 h-4 rounded-full border-2 border-[#181715] border-t-transparent animate-spin" aria-hidden />
                    <span className="flex-1">Looking things up. This can take up to a minute.</span>
                    <Button size="sm" variant="outline" icon={<Square size={11} />} onClick={() => abortRef.current?.abort()}>
                      Cancel
                    </Button>
                  </div>
                )}
                {t.state === 'error' && (
                  <div role="alert" className="flex items-start gap-2 text-sm text-[#8E2F20]">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
                    <div className="flex-1">
                      <p>{t.error}</p>
                      {t.error !== 'Cancelled.' && (
                        <Button size="sm" variant="secondary" className="mt-2" disabled={busy} onClick={() => void ask(t.query)}>
                          Retry
                        </Button>
                      )}
                    </div>
                  </div>
                )}
                {t.state === 'done' && t.response && <AnswerView response={t.response} turnId={t.id} />}
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <form
          className="p-4 border-t border-[#E8E2D8] bg-white space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(input);
          }}
        >
          <div className="flex items-end gap-2">
            <label htmlFor="analyst-input" className="sr-only">
              Your question
            </label>
            <textarea
              id="analyst-input"
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  void ask(input);
                }
              }}
              rows={2}
              maxLength={maxInput}
              placeholder={level === 'proposal' ? 'Ask about this proposal…' : level === 'dao' && scope?.dao ? `Ask about ${scope.dao.name}…` : 'Ask about DAO governance…'}
              aria-invalid={tooShort}
              className="flex-1 resize-none rounded-md border border-[#DDD5C7] bg-white px-3 py-2 text-sm placeholder:text-[#8C867D] focus:border-[#181715] focus:outline-none"
            />
            <Button type="submit" variant="primary" disabled={!canSend} loading={busy} icon={busy ? undefined : <Send size={14} />} aria-label="Send question" />
          </div>
          <div className="flex justify-between text-[11px] text-[#7D776E]">
            <span className={tooShort ? 'text-[#8E2F20]' : ''}>{tooShort ? `Questions need at least ${MIN_LEN} characters.` : 'Enter to send · Shift+Enter for a new line'}</span>
            <span className="font-mono">
              {trimmed.length}/{maxInput}
            </span>
          </div>
        </form>
      </aside>
    </div>
  );
};
