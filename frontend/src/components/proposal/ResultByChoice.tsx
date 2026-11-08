import React from 'react';
import { formatCompact, formatPct } from '../../lib/format';
import { leadingChoiceIndex } from '../../lib/analytics';

interface ResultByChoiceProps {
  choices: string[];
  scores: number[];
  scoresTotal: number | null;
  /** voting still open: the top choice is "leading", not the winner (matches the backend's own wording rule) */
  open: boolean;
}

/** Voting power per choice, as returned by Snapshot (`choices` and `scores` line up by position). */
export const ResultByChoice: React.FC<ResultByChoiceProps> = ({ choices, scores, scoresTotal, open }) => {
  if (!choices.length || !scores.length) {
    return <p className="text-sm text-[#5C5852]">No result data is stored for this proposal yet.</p>;
  }
  const total = scoresTotal || scores.reduce((a, b) => a + b, 0);
  const lead = leadingChoiceIndex(scores);
  const rows = choices
    .map((name, i) => ({ name, score: scores[i] ?? 0, index: i }))
    .sort((a, b) => b.score - a.score);
  // Approval / ranked votes: one voter's power backs several choices, so the shares add up to more than 100%.
  const multiChoice = total > 0 && scores.reduce((a, b) => a + b, 0) > total * 1.001;

  return (
    <>
    {multiChoice && (
      <p role="note" className="mb-3 text-xs text-[#5C5852]">
        Voters could back several choices here, so each bar is the share of all voting power that backed that choice and the shares add up to more than 100%.
      </p>
    )}
    <ul className="space-y-3">
      {rows.map((r) => {
        const pct = total ? (r.score / total) * 100 : 0;
        const isLead = r.index === lead;
        return (
          <li key={`${r.index}-${r.name}`}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className={`min-w-0 break-words ${isLead ? 'font-semibold text-[#181715]' : 'text-[#4A463F]'}`}>
                {r.name}
                {isLead && (
                  <span className="ml-2 editorial-label text-[9px] text-[#23593F]">{open ? 'Leading' : 'Top choice'}</span>
                )}
              </span>
              <span className="font-mono text-xs text-[#181715] shrink-0">
                {formatCompact(r.score)} · {formatPct(pct)}
              </span>
            </div>
            <div
              className="mt-1.5 h-2 rounded-full bg-[#F0ECE3] overflow-hidden"
              role="meter"
              aria-label={`${r.name}: ${formatPct(pct)} of voting power`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(pct)}
            >
              <div className="h-full rounded-full" style={{ width: `${Math.min(100, pct)}%`, backgroundColor: isLead ? '#23593F' : '#BDB3A1' }} />
            </div>
          </li>
        );
      })}
    </ul>
    </>
  );
};
