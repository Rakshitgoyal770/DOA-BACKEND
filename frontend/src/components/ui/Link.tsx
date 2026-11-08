import React from 'react';
import { href } from '../../hooks/useRouter';

interface LinkProps extends Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  to: string;
  params?: Record<string, string | number | null | undefined>;
}

/** Internal link: a real <a href="#/…"> so middle-click, copy-link and back/forward all work. */
export const Link: React.FC<LinkProps> = ({ to, params, children, ...rest }) => (
  <a href={href(to, params)} {...rest}>
    {children}
  </a>
);

/** Link to another site; always opens safely in a new tab. */
export const ExternalLink: React.FC<React.AnchorHTMLAttributes<HTMLAnchorElement>> = ({ children, ...rest }) => (
  <a target="_blank" rel="noopener noreferrer" {...rest}>
    {children}
  </a>
);
