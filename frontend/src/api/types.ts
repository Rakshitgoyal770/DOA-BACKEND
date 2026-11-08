/**
 * Response shapes of the backend, copied from its Pydantic models and route code
 * (each feature's routes.py). Nothing here is invented: if a field is not returned by
 * the API it is not in these types.
 */

export type ProposalState = 'active' | 'closed' | 'pending';
export type Confidence = 'low' | 'medium' | 'high' | 'certain';

/** A vote's choice, decoded to names by the backend: "For", ["For","B"], {"For": 2}. */
export type Ballot = string | number | string[] | Record<string, number> | null;

// ── /daos ────────────────────────────────────────────────────────────────────

export interface DaoSummary {
  id: string;
  name: string;
  network: string | null;
  about: string | null;
  proposals_ingested: number;
  proposals_with_forum: number;
  forum_coverage_pct: number;
  avg_silence_ratio_pct: number;
  avg_top_choice_share_pct: number;
}

export interface TopProposal {
  id: string;
  title: string;
  state: string | null;
  votes_count: number | null;
  forum_posters: number;
  silence_ratio_pct: number | null;
  top_choice_share_pct: number | null;
  link: string | null;
}

export interface DaoDetail extends DaoSummary {
  space_snapshot_url: string;
  top_proposals: TopProposal[];
}

// ── /proposals ───────────────────────────────────────────────────────────────

export interface ProposalSummary {
  id: string;
  space_id: string;
  title: string;
  state: ProposalState | null;
  votes_count: number | null;
  forum_posters: number;
  silence_ratio_pct: number | null;
  top_choice_share_pct: number | null;
  scores_total: number | null;
  link: string | null;
  discussion_url: string | null;
  author: string | null;
  start_ts: number | null;
  end_ts: number | null;
}

export interface ProposalDetail extends ProposalSummary {
  /** first 500 characters (kept by the backend for older clients) */
  body_preview: string;
  /** the complete proposal text, markdown as written on Snapshot */
  body: string;
  choices: string[];
  scores: number[];
  votes_ingested: number;
}

export interface VoterEntry {
  voter: string;
  voting_power: number;
  power_share_pct: number;
  choice: Ballot;
}

export interface ConcentrationReport {
  proposal_id: string;
  title: string;
  total_voters_ingested: number;
  total_voting_power: number;
  top_n: number;
  top_n_power: number;
  top_n_share_pct: number;
  top_voters: VoterEntry[];
  note: string;
}

/** A ballot exactly as Snapshot stores it: 1-based choice numbers (single, list, or {number: weight}). */
export type RawBallot = number | number[] | Record<string, number> | null;

// ── /proposals/{id}/posts ────────────────────────────────────────────────────

export type PostOrder = 'thread' | 'newest' | 'voting_power';

export interface PostAuthor {
  wallet_address: string;
  /** verified both ways, else null */
  ens_name: string | null;
  /** how sure the username -> wallet link is; low = a guess */
  confidence_level: Confidence;
  resolution_method: string;
}

export interface PostVote {
  choice: Ballot;
  choice_raw: RawBallot;
  voting_power: number;
  power_share_pct: number | null;
  /** unix seconds */
  voted_at: number | null;
  /** what the voter wrote on Snapshot with the vote, if anything */
  reason: string | null;
}

export interface ForumPost {
  post_id: number;
  topic_id: number | null;
  post_number: number | null;
  username: string;
  /** the full post, HTML removed */
  content: string;
  created_at: string | null;
  post_url: string | null;
  /** null: the username has no wallet link */
  author: PostAuthor | null;
  /** null: the linked wallet did not vote on this proposal (or there is no link) */
  vote: PostVote | null;
}

export interface ProposalPosts {
  proposal_id: string;
  title: string;
  discussion_url: string | null;
  total: number;
  posters: number;
  linked_posts: number;
  posts_with_vote: number;
  limit: number;
  offset: number;
  order: PostOrder;
  posts: ForumPost[];
}

// ── /proposals/{id}/votes ────────────────────────────────────────────────────

export type VoteSort = 'voting_power' | 'voting_power_asc' | 'newest' | 'oldest';

export interface VoteRow {
  voter: string;
  ens_name: string | null;
  forum_users: { username: string; confidence_level: Confidence }[];
  choice: Ballot;
  choice_raw: RawBallot;
  voting_power: number;
  power_share_pct: number | null;
  /** when the vote was cast (unix seconds) */
  created_ts: number | null;
  fetched_at: string | null;
  /** the voter's written reason on Snapshot (null: none, or not read yet) */
  reason: string | null;
}

export interface ProposalVotes {
  proposal_id: string;
  title: string;
  choices: string[];
  expected_votes: number;
  stored_votes: number;
  complete: boolean;
  total_voting_power: number;
  /** votes kept by q / choice / with_reason; page with offset < matched */
  matched: number;
  /** false while some stored votes predate reason storage */
  reasons_complete: boolean;
  limit: number;
  offset: number;
  sort: VoteSort;
  q: string | null;
  choice: number | null;
  with_reason: boolean;
  votes: VoteRow[];
}

// ── /identities ──────────────────────────────────────────────────────────────

export interface IdentityStats {
  forum_users: number;
  resolved: number;
  coverage_pct: number;
  medium_plus: number;
  medium_plus_pct: number;
  forum_posts: number;
  posts_by_linked_users: number;
  posts_coverage_pct: number;
  posts_with_voting_power: number;
  by_method: Record<string, number>;
  by_confidence: Record<string, number>;
  by_dao: { space_id: string; name: string; forum_users: number; linked_users: number }[];
}

export interface IdentityListItem {
  forum_username: string;
  wallet_address: string;
  confidence_level: Confidence;
  resolution_method: string;
  resolved_at: string;
  ens_name: string | null;
  post_count: number;
}

export interface IdentityList {
  total: number;
  limit: number;
  offset: number;
  items: IdentityListItem[];
}

export interface IdentityDetail {
  forum_username: string;
  wallet_address: string;
  confidence_level: Confidence;
  resolution_method: string;
  resolved_at: string;
  ens_name: string | null;
  post_count: number;
  votes: { proposal_id: string; title: string; vp: number; choice: Ballot }[];
}

export interface ProposalParticipant {
  username: string;
  posts: number;
  wallet_address: string | null;
  confidence_level: Confidence | null;
  resolution_method: string | null;
  ens_name: string | null;
  voting_power: number | null;
  choice: Ballot;
}

export interface ProposalParticipants {
  proposal_id: string;
  title: string;
  space_id: string;
  total_voters: number | null;
  forum_posters: number;
  linked_posters: number;
  linked_pct: number;
  posters_who_voted: number;
  participants: ProposalParticipant[];
}

export interface WalletIdentity {
  wallet_address: string;
  ens_name: string | null;
  forum_users: {
    forum_username: string;
    wallet_address: string;
    confidence_level: Confidence;
    resolution_method: string;
    resolved_at: string;
  }[];
}

// ── /sync/status ─────────────────────────────────────────────────────────────

export interface SyncStatus {
  audit_timestamp: string;
  total_proposals: number;
  spaces: { id: string; name: string; network: string; fetched_at: string }[];
  daos: {
    space_id: string;
    count: number;
    date_range: string;
    active_count: number;
    closed_count: number;
    with_forum_url: number;
    last_fetched: string;
  }[];
  votes: {
    total_votes: number;
    proposals_with_votes: number;
    proposals_missing_votes: number;
    date_range: string;
    last_fetched: string;
    completeness: {
      complete: number;
      partial: number;
      missing: number;
      no_votes_on_snapshot: number;
      is_complete: boolean;
      incomplete_proposals: unknown[];
    };
  };
  forum: {
    total_posts: number;
    proposals_with_posts: number;
    proposals_missing_posts: number;
    date_range: string;
    last_fetched: string;
    completeness: {
      threads: number;
      complete: number;
      partial: number;
      not_fetched: number;
      error: number;
      shared_threads: number;
      is_complete: boolean;
      [key: string]: unknown;
    };
  };
}

// ── /chat ────────────────────────────────────────────────────────────────────

export interface ChatRequest {
  query: string;
  proposal_id?: string | null;
  n_results?: number;
}

export interface ChatSource {
  id: string;
  document: string;
  source_type: 'proposal_body' | 'forum_post' | string;
  proposal_id: string | null;
  author: string | null;
  voting_power: number | null;
  distance: number;
  wallet: string | null;
  ens_name: string | null;
  link_confidence: Confidence | null;
  voted: string | null;
}

export interface ChatLookup {
  tool: string;
  arguments: Record<string, unknown>;
  result: unknown;
  automatic?: boolean;
}

export interface ChatResponse {
  query: string;
  answer: string;
  provider: string;
  chunks_found: number;
  sources: ChatSource[];
  lookups: ChatLookup[];
}
