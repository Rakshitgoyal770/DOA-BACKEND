/**
 * Contract tests against a RUNNING backend. Skipped unless VITE_INTEGRATION=1.
 *
 *   uvicorn main:app --port 8000                (in the backend repo)
 *   VITE_INTEGRATION=1 npm run test:integration
 *   VITE_INTEGRATION_CHAT=1 ...                 also calls POST /chat (uses LLM quota)
 *
 * These assert that the live responses still have every field the UI reads, so a backend
 * change that would break a screen fails here first. They read data only.
 */
import { beforeAll, describe, expect, it } from 'vitest';
import { ApiError } from './client';
import { getProposalCatalogue } from './catalogue';
import { api } from './endpoints';
import type { DaoSummary, ProposalSummary } from './types';
import { computeCoverageGap } from '../lib/analytics';
import { rejection } from './testUtils';

const RUN = import.meta.env.VITE_INTEGRATION === '1';
const RUN_CHAT = import.meta.env.VITE_INTEGRATION_CHAT === '1';

const hasKeys = (obj: object, keys: string[]) => {
  for (const k of keys) expect(obj, `missing field "${k}"`).toHaveProperty(k);
};

describe.skipIf(!RUN)('backend contract', () => {
  let daos: DaoSummary[];
  let proposals: ProposalSummary[];
  let busiest: ProposalSummary;

  beforeAll(async () => {
    daos = await api.listDaos();
    proposals = await getProposalCatalogue(true);
    busiest = proposals.find((p) => (p.votes_count ?? 0) > 0) as ProposalSummary;
  });

  it('GET / health', async () => {
    const h = await api.health();
    expect(h.status).toBe('ok');
  });

  it('GET /daos', () => {
    expect(daos.length).toBeGreaterThan(0);
    hasKeys(daos[0], ['id', 'name', 'network', 'about', 'proposals_ingested', 'proposals_with_forum', 'forum_coverage_pct', 'avg_silence_ratio_pct', 'avg_top_choice_share_pct']);
  });

  it('GET /daos/{id} returns top proposals; unknown DAO is a readable 404', async () => {
    const d = await api.getDao(daos[0].id);
    hasKeys(d, ['space_snapshot_url', 'top_proposals']);
    hasKeys(d.top_proposals[0], ['id', 'title', 'state', 'votes_count', 'forum_posters', 'silence_ratio_pct', 'top_choice_share_pct', 'link']);
    const err = await rejection(api.getDao('nope.eth'));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.message).toMatch(/not in curated list/);
  });

  it('GET /proposals pages through the whole dataset with unique ids', () => {
    expect(proposals.length).toBeGreaterThan(daos.length);
    expect(new Set(proposals.map((p) => p.id)).size).toBe(proposals.length);
    hasKeys(proposals[0], ['id', 'space_id', 'title', 'state', 'votes_count', 'forum_posters', 'silence_ratio_pct', 'top_choice_share_pct', 'scores_total', 'link', 'discussion_url', 'author', 'start_ts', 'end_ts']);
  });

  it('GET /proposals filters by DAO and rejects an out-of-range limit', async () => {
    const one = await api.listProposals({ space_id: daos[0].id, limit: 3 });
    expect(one.length).toBeLessThanOrEqual(3);
    expect(one.every((p) => p.space_id === daos[0].id)).toBe(true);
    const err = await rejection(api.listProposals({ limit: 500 }));
    expect(err.status).toBe(422);
    expect(err.message).toMatch(/limit/);
  });

  it('GET /proposals/{id}: choices and scores line up', async () => {
    const p = await api.getProposal(busiest.id);
    hasKeys(p, ['body_preview', 'choices', 'scores', 'votes_ingested']);
    expect(p.choices.length).toBe(p.scores.length);
  });

  it('GET /proposals/{id}/concentration: top-N ordered, shares sane', async () => {
    const c = await api.getConcentration(busiest.id, 10);
    hasKeys(c, ['total_voters_ingested', 'total_voting_power', 'top_n_share_pct', 'top_voters', 'note']);
    expect(c.top_voters.length).toBeLessThanOrEqual(10);
    const powers = c.top_voters.map((v) => v.voting_power);
    expect([...powers].sort((a, b) => b - a)).toEqual(powers);
    expect(c.top_n_share_pct).toBeGreaterThan(0);
    expect(c.top_n_share_pct).toBeLessThanOrEqual(100);
    hasKeys(c.top_voters[0], ['voter', 'voting_power', 'power_share_pct', 'choice']);
  });

  it('concentration / detail 404 for an unknown proposal', async () => {
    const results = await Promise.all([rejection(api.getProposal('0xnope')), rejection(api.getConcentration('0xnope', 4))]);
    for (const err of results) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(404);
    }
  });

  it('GET /identities/proposal/{id} + coverage gap compute end to end', async () => {
    const [parts, conc] = await Promise.all([api.proposalParticipants(busiest.id), api.getConcentration(busiest.id, 10)]);
    hasKeys(parts, ['forum_posters', 'linked_posters', 'linked_pct', 'posters_who_voted', 'participants', 'total_voters']);
    if (parts.participants[0]) hasKeys(parts.participants[0], ['username', 'posts', 'wallet_address', 'confidence_level', 'ens_name', 'voting_power', 'choice']);
    const gap = computeCoverageGap(conc.top_voters, parts);
    expect(gap.withForumPost + gap.withoutForumPost).toBe(conc.top_voters.length);
  });

  it('GET /identities (+stats, detail, wallet lookup) are consistent', async () => {
    const stats = await api.identityStats();
    hasKeys(stats, ['forum_users', 'resolved', 'coverage_pct', 'posts_coverage_pct', 'by_method', 'by_confidence', 'by_dao']);
    const list = await api.listIdentities({ limit: 3 });
    hasKeys(list, ['total', 'limit', 'offset', 'items']);
    expect(list.total).toBe(stats.resolved);
    const first = list.items[0];
    hasKeys(first, ['forum_username', 'wallet_address', 'confidence_level', 'resolution_method', 'resolved_at', 'ens_name', 'post_count']);

    const detail = await api.getIdentity(first.forum_username);
    hasKeys(detail, ['wallet_address', 'post_count', 'votes']);
    const wallet = await api.walletIdentity(first.wallet_address);
    expect(wallet.forum_users.map((u) => u.forum_username)).toContain(first.forum_username);

    const missing = await rejection(api.getIdentity('definitely-not-a-user'));
    expect(missing.status).toBe(404);
    const filtered = await api.listIdentities({ min_confidence: 'high', limit: 50 });
    expect(filtered.items.every((i) => ['high', 'certain'].includes(i.confidence_level))).toBe(true);
    const bad = await rejection(api.listIdentities({ min_confidence: 'bogus' }));
    expect(bad.status).toBe(422);
  });

  it('GET /proposals/{id} returns the complete body next to the 500-char preview', async () => {
    const d = await api.getProposal(busiest.id);
    const preview = d.body_preview.replace(/\.\.\.$/, '');
    expect(typeof d.body).toBe('string');
    expect(d.body.startsWith(preview)).toBe(true);
  });

  it('GET /proposals/{id}/posts gives full posts with author + vote, pages, and 404s', async () => {
    const talked = [...proposals].sort((a, b) => b.forum_posters - a.forum_posters)[0];
    const j = await api.proposalPosts(talked.id, { limit: 5, order: 'voting_power' });
    hasKeys(j, ['proposal_id', 'title', 'discussion_url', 'total', 'posters', 'linked_posts', 'posts_with_vote', 'limit', 'offset', 'order', 'posts']);
    expect(j.posts.length).toBe(Math.min(5, j.total));
    hasKeys(j.posts[0], ['post_id', 'topic_id', 'post_number', 'username', 'content', 'created_at', 'post_url', 'author', 'vote']);
    if (j.posts[0].vote) hasKeys(j.posts[0].vote, ['choice', 'choice_raw', 'voting_power', 'power_share_pct', 'voted_at', 'reason']);
    expect(j.posters).toBe(talked.forum_posters); // same count as the list endpoint
    const page1 = await api.proposalPosts(talked.id, { limit: 5, offset: 0 });
    const page2 = await api.proposalPosts(talked.id, { limit: 5, offset: 5 });
    expect(page1.posts.some((p) => page2.posts.some((q) => q.post_id === p.post_id))).toBe(false);
    expect((await rejection(api.proposalPosts('0xnope'))).status).toBe(404);
    expect((await rejection(api.proposalPosts(talked.id, { limit: 201 }))).status).toBe(422);
  });

  it('GET /proposals/{id}/votes pages every vote, sorts, searches and filters', async () => {
    const v = await api.proposalVotes(busiest.id, { limit: 10 });
    hasKeys(v, ['proposal_id', 'title', 'choices', 'expected_votes', 'stored_votes', 'complete', 'total_voting_power', 'matched', 'limit', 'offset', 'sort', 'q', 'choice', 'votes']);
    hasKeys(v.votes[0], ['voter', 'ens_name', 'forum_users', 'choice', 'choice_raw', 'voting_power', 'power_share_pct', 'created_ts', 'fetched_at', 'reason']);
    hasKeys(v, ['reasons_complete', 'with_reason']);
    const reasoned = await api.proposalVotes(busiest.id, { with_reason: true, limit: 5 });
    expect(reasoned.votes.every((x) => typeof x.reason === 'string' && x.reason.trim().length > 0)).toBe(true);
    const detail = await api.getProposal(busiest.id);
    expect(v.stored_votes).toBe(detail.votes_ingested);
    const power = v.votes.map((x) => x.voting_power);
    expect(power).toEqual([...power].sort((a, b) => b - a));
    const conc = await api.getConcentration(busiest.id, 4);
    expect(v.votes.slice(0, 4).map((x) => x.voter)).toEqual(conc.top_voters.map((x) => x.voter));
    const one = await api.proposalVotes(busiest.id, { q: v.votes[0].voter.slice(2, 10) });
    expect(one.votes.some((x) => x.voter === v.votes[0].voter)).toBe(true);
    const byChoice = await api.proposalVotes(busiest.id, { choice: 1, limit: 1 });
    expect(byChoice.matched).toBeLessThanOrEqual(v.matched);
    expect((await rejection(api.proposalVotes(busiest.id, { choice: detail.choices.length + 1 }))).status).toBe(422);
    expect((await rejection(api.proposalVotes('0xnope'))).status).toBe(404);
  });

  it('GET /sync/status', async () => {
    const s = await api.syncStatus();
    hasKeys(s, ['audit_timestamp', 'total_proposals', 'spaces', 'daos', 'votes', 'forum']);
    expect(s.total_proposals).toBe(proposals.length);
    hasKeys(s.votes, ['total_votes', 'completeness', 'last_fetched', 'date_range']);
    hasKeys(s.forum, ['total_posts', 'completeness', 'last_fetched', 'date_range']);
    hasKeys(s.daos[0], ['space_id', 'count', 'active_count', 'closed_count', 'last_fetched', 'date_range']);
  });

  it('POST /chat validates input before any LLM call (422 for a too-short question)', async () => {
    const err = await rejection(api.chat({ query: 'a' }));
    expect(err.status).toBe(422);
    expect(err.message).toMatch(/at least 3 characters/);
  });

  it.skipIf(!RUN_CHAT)('POST /chat answers with sources / lookups arrays', async () => {
    const r = await api.chat({ query: 'Which proposal had the most voters?', proposal_id: null });
    hasKeys(r, ['answer', 'provider', 'chunks_found', 'sources', 'lookups']);
    expect(typeof r.answer).toBe('string');
    expect(r.answer.length).toBeGreaterThan(10);
    expect(Array.isArray(r.sources)).toBe(true);
    expect(Array.isArray(r.lookups)).toBe(true);
    for (const l of r.lookups) hasKeys(l, ['tool', 'arguments', 'result']);
  }, 130_000);
});
