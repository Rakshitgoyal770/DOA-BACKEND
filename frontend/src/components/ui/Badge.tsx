import React from 'react';
import type { Confidence } from '../../api/types';
import { STATUS_LABEL, type DisplayStatus } from '../../lib/status';

export type BadgeVariant = 'active' | 'passed' | 'closed' | 'warning' | 'for' | 'against' | 'abstain' | 'verified' | 'neutral';

const VARIANTS: Record<BadgeVariant, string> = {
  active: 'bg-[#E9F2F7] text-[#164054] border-[#BDD8E5]',
  passed: 'bg-[#EAF4EE] text-[#23593F] border-[#BCD9C8]',
  closed: 'bg-[#F0ECE3] text-[#5C5852] border-[#DDD5C7]',
  warning: 'bg-[#FEF6EA] text-[#8C5814] border-[#F5DCB5]',
  for: 'bg-[#EAF4EE] text-[#23593F] border-[#BCD9C8]',
  against: 'bg-[#FBECE8] text-[#8E2F20] border-[#F0C3BA]',
  abstain: 'bg-[#FEF6EA] text-[#8C5814] border-[#F5DCB5]',
  verified: 'bg-[#EEF1F8] text-[#243260] border-[#CCD6ED]',
  neutral: 'bg-[#F4F0E8] text-[#5C5852] border-[#E2DDD3]',
};

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
  size?: 'sm' | 'md';
  title?: string;
}

export const Badge: React.FC<BadgeProps> = ({ children, variant = 'neutral', className = '', size = 'md', title }) => (
  <span
    title={title}
    className={`inline-flex items-center gap-1 font-medium font-sans border rounded-[4px] tracking-wide uppercase whitespace-nowrap ${
      size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2.5 py-1 text-xs'
    } ${VARIANTS[variant]} ${className}`}
  >
    {variant === 'active' && <span className="w-1.5 h-1.5 rounded-full bg-[#1E4D65] animate-pulse" aria-hidden />}
    {children}
  </span>
);

const STATUS_VARIANT: Record<DisplayStatus, BadgeVariant> = {
  active: 'active',
  pending: 'neutral',
  closed: 'closed',
  ended: 'warning',
};

export const StatusBadge: React.FC<{ status: DisplayStatus; size?: 'sm' | 'md' }> = ({ status, size = 'sm' }) => (
  <Badge
    variant={STATUS_VARIANT[status]}
    size={size}
    title={status === 'ended' ? 'Voting has ended; final result not yet synced to our database.' : undefined}
  >
    {STATUS_LABEL[status]}
  </Badge>
);

const CONFIDENCE_VARIANT: Record<Confidence, BadgeVariant> = {
  certain: 'verified',
  high: 'passed',
  medium: 'warning',
  low: 'against',
};

const CONFIDENCE_HINT: Record<Confidence, string> = {
  certain: 'Certain: confirmed by a registry or signed link.',
  high: 'High: strong evidence, e.g. a matching ENS name whose wallet voted in this DAO.',
  medium: 'Medium: a likely but unverified match.',
  low: 'Low: weak evidence; treat as a guess.',
};

export const ConfidenceBadge: React.FC<{ level: Confidence | null | undefined }> = ({ level }) => {
  if (!level) return <Badge size="sm">Not linked</Badge>;
  return (
    <Badge variant={CONFIDENCE_VARIANT[level]} size="sm" title={CONFIDENCE_HINT[level]}>
      {level}
    </Badge>
  );
};
