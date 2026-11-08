import { useMemo, useSyncExternalStore } from 'react';

/**
 * A tiny hash router. Every screen has a real URL (`#/proposal/0x…`), so links can be
 * shared, opened in a new tab and used with the browser's back button, with no
 * extra dependency and no server-side routing config.
 */
export interface Route {
  /** e.g. "/proposal/0xabc" */
  path: string;
  /** ["proposal", "0xabc"] (URL-decoded) */
  segments: string[];
  query: URLSearchParams;
}

function subscribe(callback: () => void): () => void {
  window.addEventListener('hashchange', callback);
  return () => window.removeEventListener('hashchange', callback);
}

const getHash = () => window.location.hash;

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, '') || '/';
  const [pathPart, queryPart = ''] = raw.split('?');
  const path = pathPart.startsWith('/') ? pathPart : `/${pathPart}`;
  const segments = path
    .split('/')
    .filter(Boolean)
    .map((s) => {
      try {
        return decodeURIComponent(s);
      } catch {
        return s;
      }
    });
  return { path, segments, query: new URLSearchParams(queryPart) };
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, getHash, () => '');
  return useMemo(() => parseHash(hash), [hash]);
}

/** Build a `#/path?x=y` link. Empty / null params are dropped. */
export function href(path: string, params?: Record<string, string | number | null | undefined>): string {
  const query = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== null && v !== undefined && v !== '') query.set(k, String(v));
    }
  }
  const qs = query.toString();
  return `#${path}${qs ? `?${qs}` : ''}`;
}

export function navigate(to: string, { replace = false } = {}): void {
  const target = to.startsWith('#') ? to : `#${to}`;
  if (replace) {
    window.history.replaceState(null, '', target);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  } else {
    window.location.hash = target;
  }
}
