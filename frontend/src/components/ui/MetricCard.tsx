import React from 'react';

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  subtext?: React.ReactNode;
  icon?: React.ReactNode;
  className?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({ label, value, subtext, icon, className = '' }) => (
  <div className={`surface-card p-4 flex flex-col justify-between ${className}`}>
    <div className="flex items-center justify-between mb-2 gap-2">
      <span className="editorial-label text-[11px] text-[#8C867D]">{label}</span>
      {icon && <span className="text-[#8C867D]">{icon}</span>}
    </div>
    <div className="text-2xl font-serif font-medium text-[#181715] tracking-tight mb-1 break-words">{value}</div>
    {subtext && <span className="text-xs text-[#5C5852] leading-snug">{subtext}</span>}
  </div>
);
