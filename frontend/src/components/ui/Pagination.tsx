import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from './Button';

interface PaginationProps {
  page: number; // 0-based
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
}

export const Pagination: React.FC<PaginationProps> = ({ page, pageSize, total, onChange }) => {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  const from = page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 pt-4 text-xs text-[#5C5852]">
      <span>
        {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" disabled={page <= 0} onClick={() => onChange(page - 1)} icon={<ChevronLeft size={13} />}>
          Prev
        </Button>
        <span className="font-mono">
          {page + 1} / {pages}
        </span>
        <Button size="sm" variant="outline" disabled={page >= pages - 1} onClick={() => onChange(page + 1)}>
          Next <ChevronRight size={13} />
        </Button>
      </div>
    </nav>
  );
};
