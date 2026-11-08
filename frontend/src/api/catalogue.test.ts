import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearCatalogueCache, getProposalCatalogue } from './catalogue';

const proposal = (i: number) => ({ id: `0x${i}`, space_id: 'ens.eth', title: `P${i}` });

function mockPages(sizes: number[]) {
  let call = 0;
  const fetchMock = vi.fn(async (url: string) => {
    const skip = Number(new URL(url).searchParams.get('skip'));
    const size = sizes[call++] ?? 0;
    return new Response(JSON.stringify(Array.from({ length: size }, (_, i) => proposal(skip + i))), { status: 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

beforeEach(() => clearCatalogueCache());
afterEach(() => vi.unstubAllGlobals());

describe('getProposalCatalogue', () => {
  it('pages with limit=100 until a short page arrives', async () => {
    const fetchMock = mockPages([100, 100, 18]);
    const all = await getProposalCatalogue();
    expect(all).toHaveLength(218);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const urls = fetchMock.mock.calls.map((c) => new URL(c[0]));
    expect(urls.map((u) => u.searchParams.get('skip'))).toEqual(['0', '100', '200']);
    expect(urls.every((u) => u.searchParams.get('limit') === '100')).toBe(true);
  });

  it('makes one request when the first page is short', async () => {
    const fetchMock = mockPages([18]);
    expect(await getProposalCatalogue()).toHaveLength(18);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('shares one in-flight request between concurrent callers, then serves from cache', async () => {
    const fetchMock = mockPages([5]);
    const [a, b] = await Promise.all([getProposalCatalogue(), getProposalCatalogue()]);
    expect(a).toBe(b);
    await getProposalCatalogue();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('refetches when forced, and does not cache a failure', async () => {
    mockPages([3]);
    await getProposalCatalogue();
    const fetchMock = mockPages([4]);
    expect(await getProposalCatalogue(true)).toHaveLength(4);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    clearCatalogueCache();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('down')));
    await expect(getProposalCatalogue()).rejects.toThrow();
    const recovered = mockPages([2]);
    expect(await getProposalCatalogue()).toHaveLength(2);
    expect(recovered).toHaveBeenCalledTimes(1);
  });
});
