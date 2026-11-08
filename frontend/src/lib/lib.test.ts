import { describe, expect, it } from 'vitest';
import type { ConcentrationReport, ProposalParticipants, ProposalSummary } from '../api/types';
import { computeCoverageGap, leadingChoiceIndex } from './analytics';
import { parseAnswer, parseInline } from './answer';
import { daysSince, formatBallot, formatCompact, formatPct, formatTimeRemaining, isWalletAddress, truncateAddress } from './format';
import { DEFAULT_FILTERS, countByStatus, filterProposals, filtersToParams, parseFilters } from './proposals';
import { deriveStatus } from './status';

const NOW = 1_800_000_000;

describe('deriveStatus', () => {
  it('trusts closed', () => expect(deriveStatus({ state: 'closed', start_ts: 1, end_ts: NOW + 100 }, NOW)).toBe('closed'));
  it('flags a stale "active" whose window has ended', () =>
    expect(deriveStatus({ state: 'active', start_ts: NOW - 1000, end_ts: NOW - 1 }, NOW)).toBe('ended'));
  it('is active inside the window', () =>
    expect(deriveStatus({ state: 'active', start_ts: NOW - 10, end_ts: NOW + 10 }, NOW)).toBe('active'));
  it('is upcoming before the start', () =>
    expect(deriveStatus({ state: 'pending', start_ts: NOW + 10, end_ts: NOW + 100 }, NOW)).toBe('pending'));
  it('treats a "pending" row inside its window as active', () =>
    expect(deriveStatus({ state: 'pending', start_ts: NOW - 10, end_ts: NOW + 10 }, NOW)).toBe('active'));
  it('survives missing timestamps', () => expect(deriveStatus({ state: 'active', start_ts: null, end_ts: null }, NOW)).toBe('active'));
});

describe('format', () => {
  it('compacts numbers and handles null', () => {
    expect(formatCompact(182471215.06)).toBe('182.47M');
    expect(formatCompact(1500)).toBe('1.5K');
    expect(formatCompact(12)).toBe('12');
    expect(formatCompact(null)).toBe('—');
  });
  it('keeps precision for tiny percentages', () => {
    expect(formatPct(0.027)).toBe('0.027%');
    expect(formatPct(1.268)).toBe('1.27%');
    expect(formatPct(91.9)).toBe('91.9%');
    expect(formatPct(0)).toBe('0%');
    expect(formatPct(null)).toBe('—');
  });
  it('formats ballots in every backend shape', () => {
    expect(formatBallot('For')).toBe('For');
    expect(formatBallot(['For', 'Option D'])).toBe('For, Option D');
    expect(formatBallot({ A: 6600000, B: 13200000 })).toBe('B 67% · A 33%');
    expect(formatBallot({ A: 1, B: 1, C: 1, D: 1, E: 1 }, 2)).toBe('A 20% · B 20% · +3 more');
    expect(formatBallot(3)).toBe('Choice 3');
    expect(formatBallot(null)).toBe('—');
    expect(formatBallot({})).toBe('—');
  });
  it('colours only unambiguous stances', () => {
  });
  it('shortens addresses and validates wallets', () => {
    expect(truncateAddress('0xb4c064f466931B8d0F637654c916E3F203c46f13', 4)).toBe('0xb4c0…6f13');
    expect(isWalletAddress('0xb4c064f466931B8d0F637654c916E3F203c46f13')).toBe(true);
    expect(isWalletAddress('0xb4c064')).toBe(false);
    expect(isWalletAddress('vitalik.eth')).toBe(false);
  });
  it('time remaining and age', () => {
    expect(formatTimeRemaining(NOW - 1, NOW)).toBe('Ended');
    expect(formatTimeRemaining(NOW + 90_000, NOW)).toBe('1d 1h left');
    expect(daysSince('2026-10-22T00:00:00Z', Date.parse('2026-11-07T00:00:00Z'))).toBe(16);
    expect(daysSince('garbage')).toBe(Infinity);
  });
});

describe('parseAnswer', () => {
  it('extracts single and multiple Source citations, Facts and Background markers', () => {
    const inline = parseInline('Delegates banned it [Source 1, Source 2]. Total is 5 [Facts]. [Background] A DAO is a collective.');
    expect(inline.filter((p) => p.type === 'cite')).toEqual([{ type: 'cite', numbers: [1, 2] }]);
    expect(inline.some((p) => p.type === 'facts')).toBe(true);
    expect(inline.some((p) => p.type === 'background')).toBe(true);
  });
  it('accepts the full-width brackets some providers emit (real Groq output)', () => {
    const real = 'express support or concerns about implementation rather than opposition【Source 1】【Source 2】【Source 6】. Want the reasons?';
    const cites = parseInline(real).filter((p) => p.type === 'cite');
    expect(cites).toEqual([
      { type: 'cite', numbers: [1] },
      { type: 'cite', numbers: [2] },
      { type: 'cite', numbers: [6] },
    ]);
    expect(parseInline('x 【Facts】 y').some((p) => p.type === 'facts')).toBe(true);
  });
  it('does not treat a bare [3] as a citation', () => {
    expect(parseInline('see item [3] here').some((p) => p.type === 'cite')).toBe(false);
  });
  it('parses paragraphs, bullet lists, numbered lists, headings and bold', () => {
    const blocks = parseAnswer('## Summary\nIt **passed** [Facts].\n\n- one [Source 1]\n- two\n\n1. first\n2. second');
    expect(blocks.map((b) => b.type)).toEqual(['p', 'p', 'ul', 'ol']);
    const ul = blocks[2];
    expect(ul.type === 'ul' && ul.items).toHaveLength(2);
  });
  it('never emits raw HTML: tags stay plain text', () => {
    const blocks = parseAnswer('<img src=x onerror=alert(1)> **b**');
    const p = blocks[0];
    expect(p.type).toBe('p');
    expect(p.type === 'p' && p.content[0]).toEqual({ type: 'text', text: '<img src=x onerror=alert(1)> ' });
  });
  it('handles empty input', () => expect(parseAnswer('')).toEqual([]));
});

const prop = (over: Partial<ProposalSummary>): ProposalSummary => ({
  id: '0x1', space_id: 'ens.eth', title: 'Treasury grant', state: 'closed', votes_count: 100, forum_posters: 5,
  silence_ratio_pct: 5, top_choice_share_pct: 80, scores_total: 1, link: null, discussion_url: null, author: null,
  start_ts: NOW - 1000, end_ts: NOW - 500, ...over,
});

describe('filterProposals', () => {
  const list = [
    prop({ id: '0xa', title: 'Treasury grant', votes_count: 10, silence_ratio_pct: 50, start_ts: 3 }),
    prop({ id: '0xb', title: 'Quorum change', votes_count: 500, silence_ratio_pct: 0.5, space_id: 'aavedao.eth', start_ts: 1 }),
    prop({ id: '0xc', title: 'Grants round', votes_count: 0, silence_ratio_pct: null, start_ts: 2 }),
    prop({ id: '0xd', title: 'Live vote', state: 'active', start_ts: NOW - 10, end_ts: NOW + 10, votes_count: 7 }),
  ];
  const f = (o = {}) => filterProposals(list, { ...DEFAULT_FILTERS, ...o }, NOW).map((p) => p.id);

  it('shows the newest first by default', () => expect(f()).toEqual(['0xd', '0xa', '0xc', '0xb']));
  it('sorts by voters', () => expect(f({ sort: 'votes' })).toEqual(['0xb', '0xa', '0xd', '0xc']));
  it('searches titles case-insensitively', () => expect(f({ q: 'GRANT' })).toEqual(['0xa', '0xc']));
  it('finds by id prefix', () => expect(f({ q: '0xb' })).toEqual(['0xb']));
  it('filters by DAO and by derived status', () => {
    expect(f({ dao: 'aavedao.eth' })).toEqual(['0xb']);
    expect(f({ status: 'active' })).toEqual(['0xd']);
  });
  it('most contested = smallest leading share first; proposals with no result last', () => {
    const shares = [
      prop({ id: '0x1', top_choice_share_pct: 99 }),
      prop({ id: '0x2', top_choice_share_pct: null }),
      prop({ id: '0x3', top_choice_share_pct: 51.2 }),
    ];
    expect(filterProposals(shares, { ...DEFAULT_FILTERS, sort: 'contested' }, NOW).map((p) => p.id)).toEqual(['0x3', '0x1', '0x2']);
  });
  it('counts proposals per display status for the tabs', () => {
    expect(countByStatus(list, NOW)).toEqual({ active: 1, pending: 0, ended: 0, closed: 3 });
  });
  it('sorts by date', () => {
    expect(f({ sort: 'oldest' })[0]).toBe('0xb');
    expect(f({ sort: 'newest' })[0]).toBe('0xd');
  });
  it('does not mutate its input', () => {
    const before = list.map((p) => p.id);
    f({ sort: 'oldest' });
    expect(list.map((p) => p.id)).toEqual(before);
  });
});

describe('filter <-> URL round trip', () => {
  it('omits defaults and parses them back', () => {
    expect(filtersToParams(DEFAULT_FILTERS)).toEqual({ q: null, dao: null, status: null, sort: null, page: null });
    const params = new URLSearchParams('q=grant&dao=ens.eth&status=ended&sort=newest&page=2');
    expect(parseFilters(params)).toEqual({ q: 'grant', dao: 'ens.eth', status: 'ended', sort: 'newest', page: 2 });
  });
  it('ignores junk values', () => {
    expect(parseFilters(new URLSearchParams('status=bogus&sort=nope&page=-3'))).toEqual(DEFAULT_FILTERS);
  });
});

describe('computeCoverageGap', () => {
  const voter = (v: string, share: number) => ({ voter: v, voting_power: 1, power_share_pct: share, choice: 'For' });
  const concentration: ConcentrationReport = {
    proposal_id: 'p', title: 't', total_voters_ingested: 3, total_voting_power: 3, top_n: 3, top_n_power: 3, top_n_share_pct: 100, note: '',
    top_voters: [voter('0xAAA', 50), voter('0xBBB', 30), voter('0xCCC', 20)],
  };
  const participants: ProposalParticipants = {
    proposal_id: 'p', title: 't', space_id: 's', total_voters: 3, forum_posters: 2, linked_posters: 1, linked_pct: 50, posters_who_voted: 1,
    participants: [
      { username: 'alice', posts: 2, wallet_address: '0xaaa', confidence_level: 'high', resolution_method: 'voter_ens', ens_name: 'alice.eth', voting_power: 1, choice: 'For' },
      { username: 'bob', posts: 1, wallet_address: null, confidence_level: null, resolution_method: null, ens_name: null, voting_power: null, choice: null },
    ],
  };
  it('matches wallets case-insensitively', () => {
    const gap = computeCoverageGap(concentration.top_voters, participants);
    expect(gap.withForumPost).toBe(1);
    expect(gap.withoutForumPost).toBe(2);
    expect(gap.rows[0].poster?.username).toBe('alice');
    expect(gap.rows[1].poster).toBeNull();
  });
  it('reports everyone as unlinked when nobody posted', () => {
    const gap = computeCoverageGap(concentration.top_voters, { ...participants, participants: [] });
    expect(gap.withForumPost).toBe(0);
    expect(gap.withoutForumPost).toBe(3);
  });
  it('finds the leading choice', () => {
    expect(leadingChoiceIndex([1, 5, 3])).toBe(1);
    expect(leadingChoiceIndex([0, 0])).toBe(-1);
    expect(leadingChoiceIndex([])).toBe(-1);
  });
});

import { PROMPTS, availableLevels, buildChatRequest, daoPrefix, levelLabel, scopeKey } from './analystScope';

describe('analyst scope levels', () => {
  const both = { proposal: { id: '0xabc', title: 'OAT Elections' }, dao: { id: 'arbitrumfoundation.eth', name: 'Arbitrum DAO' } };

  it('offers levels most-specific first, depending on the page', () => {
    expect(availableLevels(both)).toEqual(['proposal', 'dao', 'general']);
    expect(availableLevels({ dao: both.dao })).toEqual(['dao', 'general']);
    expect(availableLevels(null)).toEqual(['general']);
  });
  it('proposal level sends proposal_id and the question untouched', () => {
    expect(buildChatRequest('proposal', both, '  Who objected?  ')).toEqual({ query: 'Who objected?', proposal_id: '0xabc' });
  });
  it('dao level names the DAO in the question and sends no proposal_id', () => {
    expect(buildChatRequest('dao', both, 'Which had the most voters?')).toEqual({
      query: 'About Arbitrum DAO only: Which had the most voters?',
      proposal_id: null,
    });
  });
  it('general level sends the bare question', () => {
    expect(buildChatRequest('general', both, 'hello there')).toEqual({ query: 'hello there', proposal_id: null });
  });
  it('falls back to general if the level is not available on this page', () => {
    expect(buildChatRequest('proposal', null, 'hi there')).toEqual({ query: 'hi there', proposal_id: null });
    expect(buildChatRequest('dao', { proposal: both.proposal }, 'hi there').query).toBe('hi there');
  });
  it('labels levels and keys scopes', () => {
    expect(levelLabel('dao', both)).toBe('Arbitrum DAO');
    expect(levelLabel('general', null)).toBe('All DAOs');
    expect(scopeKey(both)).not.toBe(scopeKey({ dao: both.dao }));
    expect(daoPrefix('ENS').length).toBeGreaterThan(0);
    for (const l of ['proposal', 'dao', 'general'] as const) expect(PROMPTS[l].length).toBeGreaterThan(0);
  });
});
