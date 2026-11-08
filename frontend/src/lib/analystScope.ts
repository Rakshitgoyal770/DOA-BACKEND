import type { ChatRequest } from '../api/types';

/**
 * The analyst can be asked at three levels:
 *   proposal : about one proposal  -> the backend's native `proposal_id` filter
 *   dao      : about one DAO       -> NO backend parameter exists; we name the DAO in the question,
 *                                    and the agent passes it to its lookups as `dao=...`
 *                                    (verified: "About Arbitrum DAO only: ..." makes list_proposals run with dao=arbitrum)
 *   general  : across all DAOs
 */
export type Level = 'proposal' | 'dao' | 'general';

export interface AnalystScope {
  proposal?: { id: string; title: string };
  dao?: { id: string; name: string };
}

export const LEVEL_ORDER: Level[] = ['proposal', 'dao', 'general'];

/** Levels the current page offers, most specific first. "general" is always available. */
export function availableLevels(scope: AnalystScope | null): Level[] {
  return LEVEL_ORDER.filter((l) => l === 'general' || (l === 'proposal' && scope?.proposal) || (l === 'dao' && scope?.dao));
}

/** Identity of a scope, so a user's level choice resets when they open the analyst from somewhere else. */
export function scopeKey(scope: AnalystScope | null): string {
  return `${scope?.proposal?.id ?? ''}|${scope?.dao?.id ?? ''}`;
}

export function daoPrefix(daoName: string): string {
  return `About ${daoName} only: `;
}

/** The exact `/chat` request body for a question at a level. */
export function buildChatRequest(level: Level, scope: AnalystScope | null, query: string): ChatRequest {
  const q = query.trim();
  if (level === 'proposal' && scope?.proposal) return { query: q, proposal_id: scope.proposal.id };
  if (level === 'dao' && scope?.dao) return { query: daoPrefix(scope.dao.name) + q, proposal_id: null };
  return { query: q, proposal_id: null };
}

export function levelLabel(level: Level, scope: AnalystScope | null): string {
  if (level === 'proposal') return 'This proposal';
  if (level === 'dao') return scope?.dao?.name ?? 'This DAO';
  return 'All DAOs';
}

export const PROMPTS: Record<Level, string[]> = {
  proposal: ['Summarize what this proposal asks for.', 'Who argued against this and why?', 'Who are the biggest voters and how did they vote?'],
  dao: ['Which proposal had the most voters?', 'Which proposals were the closest votes?', 'How much forum discussion do votes here get compared to voters?'],
  general: [
    'Which proposals had the most voters?',
    'Which DAO has the least forum discussion compared to voters?',
    'Who are the largest voters on the most recent Arbitrum proposal?',
  ],
};
