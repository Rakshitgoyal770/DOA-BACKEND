/**
 * How links and images inside a proposal's text are resolved.
 *
 * Proposals are written on Snapshot, which stores pictures as `ipfs://<cid>/<file>`. A browser
 * cannot open that address, so we read it through the public gateway Snapshot's own site uses
 * (checked on 2026-11-07: it served every image tested; ipfs.io timed out and Cloudflare's
 * gateway is gone). Visitors' browsers contact that gateway directly, as they do on Snapshot.
 */
export const IPFS_GATEWAY = 'https://snapshot.4everland.link/ipfs/';

/**
 * The address to use for a link or image `url` found in a proposal's text.
 *
 * Parameters:
 *   url      - the address as written in the markdown.
 *   fallback - react-markdown's own `defaultUrlTransform`, which keeps http(s) and mailto and
 *              drops everything else (javascript:, data:, upload://, ...) by returning ''.
 * Returns '' when the address cannot be used, so the caller shows a placeholder instead.
 */
export function resolveMarkdownUrl(url: string, fallback: (url: string) => string): string {
  const ipfs = /^ipfs:\/\/(?:ipfs\/)?([A-Za-z0-9][A-Za-z0-9._~%/+=-]*)$/.exec(url.trim());
  if (ipfs) return IPFS_GATEWAY + ipfs[1];
  return fallback(url);
}
