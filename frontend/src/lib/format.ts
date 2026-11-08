import type { Ballot } from '../api/types';

/**
 * Voting power / vote counts. The backend never says which token a number is in
 * (snapshot "vp" is protocol-specific), so we never append a symbol.
 */
export function formatCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toLocaleString('en-US', { maximumFractionDigits: 1 });
}

export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value.toLocaleString('en-US');
}

/** Percentage with sensible precision: tiny values keep 2-3 decimals, large ones 1. */
export function formatPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  if (value === 0) return '0%';
  if (Math.abs(value) < 0.1) return `${value.toFixed(3)}%`;
  if (Math.abs(value) < 10) return `${value.toFixed(2)}%`;
  return `${value.toFixed(1)}%`;
}

export function truncateAddress(address: string | null | undefined, chars = 4): string {
  if (!address) return '';
  if (address.length <= chars * 2 + 2) return address;
  return `${address.slice(0, chars + 2)}…${address.slice(-chars)}`;
}

/** Unix seconds -> "Jul 9, 2026". */
export function formatDate(unixSeconds: number | null | undefined): string {
  if (!unixSeconds) return '—';
  return new Date(unixSeconds * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/** ISO string -> "Oct 22, 2026, 9:36 AM". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/** "3d 4h left" / "5h 12m left" / "Ended". */
export function formatTimeRemaining(endUnix: number | null | undefined, nowUnix = Date.now() / 1000): string {
  if (!endUnix) return '—';
  const diff = endUnix - nowUnix;
  if (diff <= 0) return 'Ended';
  const days = Math.floor(diff / 86400);
  const hours = Math.floor((diff % 86400) / 3600);
  if (days > 0) return `${days}d ${hours}h left`;
  const minutes = Math.floor((diff % 3600) / 60);
  return `${hours}h ${minutes}m left`;
}

/** Whole days since an ISO timestamp (Infinity if unparseable). */
export function daysSince(iso: string | null | undefined, now = Date.now()): number {
  if (!iso) return Infinity;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? Infinity : (now - t) / 86_400_000;
}

/** "5 days ago" for an ISO timestamp. */
export function formatAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '—';
  const days = Math.floor((now - t) / 86_400_000);
  if (days < 1) return 'today';
  if (days === 1) return 'yesterday';
  return `${days} days ago`;
}

/**
 * Turn the backend's decoded ballot into short text.
 *   "For"                       -> "For"
 *   ["For", "Option D"]         -> "For, Option D"        (approval / ranked)
 *   {"A": 6600000, "B": 13200000} -> "B 66.7% · A 33.3%"  (weighted: shares of the voter's own power)
 */
export function formatBallot(choice: Ballot | undefined, maxParts = 3): string {
  if (choice === null || choice === undefined) return '—';
  if (typeof choice === 'string') return choice;
  if (typeof choice === 'number') return `Choice ${choice}`;
  if (Array.isArray(choice)) return choice.length ? choice.join(', ') : '—';
  const entries = Object.entries(choice).filter(([, w]) => typeof w === 'number' && w > 0);
  if (!entries.length) return '—';
  const total = entries.reduce((sum, [, w]) => sum + w, 0);
  const sorted = entries.sort((a, b) => b[1] - a[1]);
  const parts = sorted.slice(0, maxParts).map(([name, w]) => `${name} ${((w / total) * 100).toFixed(0)}%`);
  const more = sorted.length - maxParts;
  return parts.join(' · ') + (more > 0 ? ` · +${more} more` : '');
}

/** How a forum user was linked to a wallet (resolved_identities.resolution_method), in words. */
const METHOD_LABEL: Record<string, string> = {
  ens_username: 'Username is an ENS name',
  voter_ens: 'Voter ENS matches username',
  profile_ens: 'ENS name in forum profile',
  profile_wallet: 'Wallet in forum profile',
  self_disclosed: 'Wallet named in own post',
  registry: 'Hand-verified',
  ens: 'ENS',
};

export function methodLabel(method: string): string {
  return METHOD_LABEL[method] ?? method.replace(/_/g, ' ');
}

export function isWalletAddress(text: string): boolean {
  return /^0x[a-fA-F0-9]{40}$/.test(text.trim());
}
