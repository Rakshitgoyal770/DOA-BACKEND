import React from 'react';

interface MeterProps {
  /** 0-100 */
  value: number;
  color?: string;
  label?: string;
  className?: string;
}

/** A thin horizontal bar for a percentage. */
export const Meter: React.FC<MeterProps> = ({ value, color = '#181715', label, className = '' }) => {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      className={`h-1.5 w-full rounded-full bg-[#EBE5DA] overflow-hidden ${className}`}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(pct)}
      aria-label={label}
    >
      <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  );
};
