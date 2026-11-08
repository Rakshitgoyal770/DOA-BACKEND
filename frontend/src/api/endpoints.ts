/**
 * One function per backend endpoint. Every call the UI makes goes through here,
 * so the full API surface the frontend depends on is visible in this file.
 *
 * Deliberately NOT wrapped (the backend has no auth, so exposing them in a public
 * UI would let any visitor start long, external-API-hitting jobs):
 *   POST /sync/run             POST /identities/resolve        GET /identities/resolve/status
 */
import { apiFetch } from './client';
import { CHAT_TIMEOUT_MS } from '../config';
import type {
  ChatRequest,
  ChatResponse,
  ConcentrationReport,
  DaoDetail,
  DaoSummary,
  IdentityDetail,
  IdentityList,
  IdentityStats,
  ProposalDetail,
  PostOrder,
  ProposalParticipants,
  ProposalPosts,
  ProposalState,
  ProposalVotes,
  VoteSort,
  ProposalSummary,
  SyncStatus,
  WalletIdentity,
} from './types';

type Opt = { signal?: AbortSignal };

export const api = {
  health: (o: Opt = {}) => apiFetch<{ status: string; service: string; version: string }>('/', o),

  // DAOs
  listDaos: (o: Opt = {}) => apiFetch<DaoSummary[]>('/daos', o),
  getDao: (spaceId: string, o: Opt = {}) => apiFetch<DaoDetail>(`/daos/${encodeURIComponent(spaceId)}`, o),

  // Proposals
  listProposals: (
    params: { space_id?: string; state?: ProposalState; limit?: number; skip?: number } = {},
    o: Opt = {},
  ) => apiFetch<ProposalSummary[]>('/proposals', { query: params, ...o }),
  getProposal: (id: string, o: Opt = {}) => apiFetch<ProposalDetail>(`/proposals/${encodeURIComponent(id)}`, o),
  getConcentration: (id: string, topN: number, o: Opt = {}) =>
    apiFetch<ConcentrationReport>(`/proposals/${encodeURIComponent(id)}/concentration`, { query: { top_n: topN }, ...o }),
  /** The forum discussion in full, each post with its author's wallet and vote (limit 1-200). */
  proposalPosts: (id: string, params: { limit?: number; offset?: number; order?: PostOrder } = {}, o: Opt = {}) =>
    apiFetch<ProposalPosts>(`/proposals/${encodeURIComponent(id)}/posts`, { query: params, ...o }),
  /** Every stored vote, paged (limit 1-500), sorted, searchable by wallet / ENS / forum name, filterable by choice. */
  proposalVotes: (
    id: string,
    params: { limit?: number; offset?: number; sort?: VoteSort; q?: string; choice?: number; with_reason?: boolean } = {},
    o: Opt = {},
  ) => apiFetch<ProposalVotes>(`/proposals/${encodeURIComponent(id)}/votes`, { query: params, ...o }),

  // Identities (forum user <-> wallet links)
  identityStats: (o: Opt = {}) => apiFetch<IdentityStats>('/identities/stats', o),
  listIdentities: (
    params: { q?: string; min_confidence?: string; method?: string; limit?: number; offset?: number } = {},
    o: Opt = {},
  ) => apiFetch<IdentityList>('/identities', { query: params, ...o }),
  getIdentity: (username: string, o: Opt = {}) => apiFetch<IdentityDetail>(`/identities/${encodeURIComponent(username)}`, o),
  proposalParticipants: (proposalId: string, o: Opt = {}) =>
    apiFetch<ProposalParticipants>(`/identities/proposal/${encodeURIComponent(proposalId)}`, o),
  walletIdentity: (wallet: string, o: Opt = {}) => apiFetch<WalletIdentity>(`/identities/wallet/${encodeURIComponent(wallet)}`, o),

  // Data audit
  syncStatus: (o: Opt = {}) => apiFetch<SyncStatus>('/sync/status', o),

  // RAG question answering
  chat: (req: ChatRequest, o: Opt = {}) =>
    apiFetch<ChatResponse>('/chat', { method: 'POST', body: req, timeoutMs: CHAT_TIMEOUT_MS, ...o }),
};
