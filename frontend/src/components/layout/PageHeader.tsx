import React from 'react';

interface PageHeaderProps {
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}

export const PageHeader: React.FC<PageHeaderProps> = ({ eyebrow, title, description, actions }) => (
  <div className="flex flex-wrap items-end justify-between gap-4">
    <div className="min-w-0 max-w-3xl">
      {eyebrow && <div className="editorial-label text-[#8C867D] mb-1.5">{eyebrow}</div>}
      <h1 className="editorial-headline text-3xl sm:text-4xl text-[#181715] break-words">{title}</h1>
      {description && <p className="text-sm text-[#4A463F] font-serif italic mt-2 leading-relaxed">{description}</p>}
    </div>
    {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
  </div>
);

/** A titled white card for a page section. */
export const Section: React.FC<{
  title: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
  id?: string;
}> = ({ title, hint, children, className = '', action, id }) => (
  <section id={id} aria-labelledby={id ? `${id}-title` : undefined} className={`p-5 sm:p-6 rounded-xl bg-white border border-[#E8E2D8] shadow-subtle ${className}`}>
    <div className="flex items-start justify-between gap-3 mb-4">
      <div>
        <h2 id={id ? `${id}-title` : undefined} className="editorial-label tracking-wider text-[#181715]">
          {title}
        </h2>
        {hint && <p className="text-xs text-[#7D776E] mt-1 max-w-xl">{hint}</p>}
      </div>
      {action}
    </div>
    {children}
  </section>
);
