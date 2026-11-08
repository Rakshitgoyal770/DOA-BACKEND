import type { Ballot } from '../api/types';

/**
 * Colour a ballot by what it means. Only a ballot for ONE named option can be read as
 * For / Against / Abstain; approval, ranked and weighted ballots stay neutral.
 */
export type Tone = 'for' | 'against' | 'abstain' | 'other';

const FOR = /^(for|yes|yae|yay|approve|support)\b/i;
const AGAINST = /^(against|no|nay|reject)\b/i;
const ABSTAIN = /^abstain/i;

export function choiceTone(name: string | null | undefined): Tone {
  const n = (name ?? '').trim();
  if (FOR.test(n)) return 'for';
  if (AGAINST.test(n)) return 'against';
  if (ABSTAIN.test(n)) return 'abstain';
  return 'other';
}

export function ballotTone(choice: Ballot | undefined): Tone {
  if (typeof choice === 'string') return choiceTone(choice);
  if (Array.isArray(choice) && choice.length === 1 && typeof choice[0] === 'string') return choiceTone(choice[0]);
  return 'other';
}

export const TONE_CLASS: Record<Tone, string> = {
  for: 'bg-[#EAF4EE] text-[#23593F] border-[#BCD9C8]',
  against: 'bg-[#FBECE8] text-[#8E2F20] border-[#F0C3BA]',
  abstain: 'bg-[#FEF6EA] text-[#8C5814] border-[#F5DCB5]',
  other: 'bg-[#F4F0E8] text-[#4A463F] border-[#E2DDD3]',
};

/** Bar colour per result row: green for "For"-like, red for "Against"-like, grey otherwise. */
export const TONE_BAR: Record<Tone, string> = { for: '#23593F', against: '#8E2F20', abstain: '#B07A2A', other: '#5C5852' };
