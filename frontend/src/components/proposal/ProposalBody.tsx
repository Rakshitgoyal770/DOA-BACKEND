import React, { useState } from 'react';
import Markdown, { defaultUrlTransform, type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { resolveMarkdownUrl } from '../../lib/markdown';

/**
 * The proposal's own text (GET /proposals/{id} `body`), rendered from the markdown its
 * author wrote on Snapshot.
 *
 * Safe by construction: react-markdown builds React elements, never injects HTML, and only
 * http(s), mailto and ipfs:// (read through a gateway, see lib/markdown.ts) addresses survive;
 * `javascript:` and `data:` links are dropped. Links open in a new tab. In-page anchors
 * ("#section") are shown as plain text, because this app uses the URL hash for its routes
 * and such a link would navigate away from the proposal. An image that cannot be loaded
 * (for example a forum `upload://` picture that was never published) shows its description.
 */
const COMPONENTS: Components = {
  a: ({ href, children }) =>
    !href || href.startsWith('#') ? (
      <span>{children}</span>
    ) : (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow">
        {children}
      </a>
    ),
  img: ({ src, alt }) => <Picture src={typeof src === 'string' ? src : ''} alt={alt ?? ''} />,
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table>{children}</table>
    </div>
  ),
};

/** A picture from the text; if it cannot be loaded, its description and a link to the original take its place. */
const Picture: React.FC<{ src: string; alt: string }> = ({ src, alt }) => {
  const [failed, setFailed] = useState(false);
  if (src && !failed) return <img src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />;
  return (
    <span className="inline-block rounded border border-dashed border-[#DDD5C7] px-2 py-1 text-xs text-[#7D776E]">
      Image not available{alt ? `: ${alt}` : ''}
      {src && (
        <>
          {' · '}
          <a href={src} target="_blank" rel="noopener noreferrer nofollow">
            open original
          </a>
        </>
      )}
    </span>
  );
};

const urlTransform = (url: string) => resolveMarkdownUrl(url, defaultUrlTransform);

export const ProposalBody: React.FC<{ markdown: string }> = ({ markdown }) => {
  if (!markdown.trim()) return <p className="text-sm text-[#5C5852]">This proposal has no description text.</p>;
  return (
    <div className="proposal-markdown">
      <Markdown remarkPlugins={[remarkGfm]} components={COMPONENTS} urlTransform={urlTransform}>
        {markdown}
      </Markdown>
    </div>
  );
};
