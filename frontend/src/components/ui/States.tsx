import React from 'react';
import { AlertTriangle, Inbox, RefreshCw, WifiOff } from 'lucide-react';
import { ApiError, isMissingEndpoint } from '../../api/client';
import { Button } from './Button';

/** Grey pulsing placeholder block. */
export const Skeleton: React.FC<{ className?: string }> = ({ className = '' }) => (
  <div className={`animate-pulse rounded bg-[#EBE5DA] ${className}`} aria-hidden />
);

/** Loading placeholder for a page body or a card. Announced to screen readers. */
export const LoadingBlock: React.FC<{ label?: string; rows?: number }> = ({ label = 'Loading', rows = 3 }) => (
  <div role="status" aria-live="polite" className="space-y-3 py-2">
    <span className="sr-only">{label}…</span>
    {Array.from({ length: rows }).map((_, i) => (
      <Skeleton key={i} className={`h-5 ${i === rows - 1 ? 'w-2/3' : 'w-full'}`} />
    ))}
  </div>
);

interface ErrorStateProps {
  error: Error;
  onRetry?: () => void;
  title?: string;
  compact?: boolean;
}

/** An API failure, with a plain-language cause and a retry button. */
export const ErrorState: React.FC<ErrorStateProps> = ({ error, onRetry, title, compact = false }) => {
  const api = error instanceof ApiError ? error : null;
  const unreachable = api?.kind === 'network' || api?.kind === 'timeout';
  const Icon = unreachable ? WifiOff : AlertTriangle;
  const outdated = isMissingEndpoint(error);
  const heading =
    title ??
    (outdated ? 'The data service is out of date' : api?.isNotFound ? 'Not found' : unreachable ? 'Cannot reach the data service' : 'Something went wrong');
  const message = outdated
    ? 'It does not have this feature yet. Restart the backend with the latest code (uvicorn main:app --port 8000), then reload this page.'
    : error.message;
  return (
    <div
      role="alert"
      className={`rounded-lg border border-[#F2C5BC] bg-[#FCEEEA] text-[#8E2F20] ${compact ? 'p-3' : 'p-5'} flex items-start gap-3`}
    >
      <Icon size={18} className="shrink-0 mt-0.5" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="font-semibold text-sm">{heading}</div>
        <p className="text-sm mt-0.5 break-words">{message}</p>
        {onRetry && (
          <Button size="sm" variant="secondary" className="mt-3" icon={<RefreshCw size={12} />} onClick={onRetry}>
            Try again
          </Button>
        )}
      </div>
    </div>
  );
};

export const EmptyState: React.FC<{ title: string; description?: React.ReactNode; action?: React.ReactNode }> = ({
  title,
  description,
  action,
}) => (
  <div className="rounded-lg border border-dashed border-[#DCD4C5] bg-[#FFFDF9] p-8 text-center">
    <Inbox size={22} className="mx-auto text-[#8C867D] mb-2" aria-hidden />
    <div className="font-serif text-lg text-[#181715]">{title}</div>
    {description && <p className="text-sm text-[#5C5852] mt-1 max-w-md mx-auto">{description}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
);

interface AsyncLike<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

/** Renders loading / error / data for an async result so pages stay declarative. */
export function AsyncBoundary<T>({
  state,
  label,
  skeleton,
  children,
}: {
  state: AsyncLike<T>;
  label?: string;
  skeleton?: React.ReactNode;
  children: (data: T) => React.ReactNode;
}) {
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />;
  if (state.data === null) return <>{skeleton ?? <LoadingBlock label={label} />}</>;
  return <>{children(state.data)}</>;
}
