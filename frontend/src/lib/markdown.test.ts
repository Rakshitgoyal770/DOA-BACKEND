import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { defaultUrlTransform } from 'react-markdown';
import { IPFS_GATEWAY, resolveMarkdownUrl } from './markdown';
import { ProposalBody } from '../components/proposal/ProposalBody';

const resolve = (u: string) => resolveMarkdownUrl(u, defaultUrlTransform);

describe('resolveMarkdownUrl', () => {
  it('reads ipfs:// pictures through the gateway Snapshot uses', () => {
    // a real address from a stored proposal (ArbOS 60 Elara)
    expect(resolve('ipfs://bafkreiaqpbuqelhng2wjwyabbz2wcae')).toBe(`${IPFS_GATEWAY}bafkreiaqpbuqelhng2wjwyabbz2wcae`);
    expect(resolve('ipfs://ipfs/QmHash/file.png')).toBe(`${IPFS_GATEWAY}QmHash/file.png`);
  });
  it('keeps ordinary links and drops anything that could run code or cannot be loaded', () => {
    expect(resolve('https://forum.arbitrum.foundation/t/1')).toBe('https://forum.arbitrum.foundation/t/1');
    expect(resolve('mailto:a@b.org')).toBe('mailto:a@b.org');
    expect(resolve('javascript:alert(1)')).toBe('');
    expect(resolve('data:text/html;base64,AAAA')).toBe('');
    expect(resolve('upload://8qUCNWzXNic6zOIz1yUgmtkpCVz.png')).toBe('');
    expect(resolve('ipfs://../../etc')).toBe('');            // no path tricks through the gateway
  });
});

describe('ProposalBody', () => {
  const html = (md: string) => renderToStaticMarkup(createElement(ProposalBody, { markdown: md }));

  it('renders headings, lists, tables and links from the markdown', () => {
    const out = html('# Summary\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n[docs](https://example.org)');
    expect(out).toContain('<h1>Summary</h1>');
    expect(out).toContain('<li>one</li>');
    expect(out).toMatch(/<table>.*<td>1<\/td>/s);
    expect(out).toContain('href="https://example.org"');
    expect(out).toContain('rel="noopener noreferrer nofollow"');
  });
  it('shows an ipfs picture through the gateway and a placeholder for one that cannot load', () => {
    const out = html('![Figure 1](ipfs://bafkrei123)\n\n![Screenshot](upload://abc.png)');
    expect(out).toContain(`src="${IPFS_GATEWAY}bafkrei123"`);
    expect(out).toContain('Image not available: Screenshot');
    expect(out).not.toContain('upload://');
  });
  it('does not run scripts or follow javascript: links', () => {
    const out = html('<script>alert(1)</script>\n\n[x](javascript:alert(1))');
    expect(out).not.toContain('<script');
    expect(out).not.toContain('javascript:');
  });
  it('keeps in-page anchors as text instead of navigating away from the proposal', () => {
    expect(html('[Rationale](#rationale)')).not.toContain('href="#rationale"');
  });
});
