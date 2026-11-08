import React from 'react';
import { EmptyState } from '../components/ui/States';
import { Link } from '../components/ui/Link';

export const NotFoundPage: React.FC = () => (
  <div className="quorum-container py-16 max-w-xl">
    <EmptyState
      title="Page not found"
      description="That address does not match anything here."
      action={
        <Link to="/" className="inline-block px-5 py-2.5 rounded-lg bg-[#181715] text-[#FAF8F5] text-xs font-semibold hover:bg-[#282623]">
          Back to home
        </Link>
      }
    />
  </div>
);
