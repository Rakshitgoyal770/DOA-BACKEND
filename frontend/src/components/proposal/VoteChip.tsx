import React from 'react';
import type { Ballot } from '../../api/types';
import { formatBallot } from '../../lib/format';
import { TONE_CLASS, ballotTone } from '../../lib/votes';

/** A ballot as a coloured chip: green For, red Against, amber Abstain, grey for anything else. */
export const VoteChip: React.FC<{ choice: Ballot; className?: string }> = ({ choice, className = '' }) => {
  const text = formatBallot(choice);
  return (
    <span
      title={text}
      className={`inline-block max-w-full truncate align-middle rounded border px-1.5 py-0.5 text-[11px] font-medium ${TONE_CLASS[ballotTone(choice)]} ${className}`}
    >
      {text}
    </span>
  );
};
