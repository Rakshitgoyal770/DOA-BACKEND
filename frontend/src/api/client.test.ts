import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiFetch, buildUrl, detailFromBody, errorMessage } from './client';
import { rejection } from './testUtils';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const respond = (status: number, body: unknown) =>
  new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('buildUrl', () => {
  it('drops empty, null and undefined params but keeps zero and false', () => {
    const url = buildUrl('/proposals', { space_id: 'ens.eth', state: '', limit: 0, skip: undefined, x: null, flag: false });
    expect(url).toContain('/proposals?');
    expect(url).toContain('space_id=ens.eth');
    expect(url).toContain('limit=0');
    expect(url).toContain('flag=false');
    expect(url).not.toContain('state=');
    expect(url).not.toContain('skip=');
    expect(url).not.toContain('x=');
  });
});

describe('detailFromBody (FastAPI error shapes)', () => {
  it('reads a string detail (HTTPException)', () => {
    expect(detailFromBody({ detail: "Proposal 'x' not found." }, 'fb')).toBe("Proposal 'x' not found.");
  });
  it('flattens 422 validation arrays and strips body/query from the location', () => {
    const body = { detail: [{ type: 'string_too_short', loc: ['body', 'query'], msg: 'String should have at least 3 characters' }] };
    expect(detailFromBody(body, 'fb')).toBe('String should have at least 3 characters');
    const nested = { detail: [{ loc: ['query', 'limit'], msg: 'must be <= 100' }] };
    expect(detailFromBody(nested, 'fb')).toBe('limit: must be <= 100');
  });
  it('falls back for anything else', () => {
    expect(detailFromBody(null, 'fb')).toBe('fb');
    expect(detailFromBody({ other: 1 }, 'fb')).toBe('fb');
    expect(detailFromBody({ detail: [] }, 'fb')).toBe('fb');
  });
});

describe('apiFetch', () => {
  it('returns parsed JSON on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(200, [{ id: 'a' }])));
    await expect(apiFetch('/daos')).resolves.toEqual([{ id: 'a' }]);
  });

  it('sends a JSON body and content-type for POST', async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    await apiFetch('/chat', { method: 'POST', body: { query: 'hello' } });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"query":"hello"}');
    expect(init.headers['Content-Type']).toBe('application/json');
  });

  it('turns a 404 into an ApiError carrying the backend message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(respond(404, { detail: "Proposal 'nope' not found." })));
    const err = await rejection(apiFetch('/proposals/nope'));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.isNotFound).toBe(true);
    expect(err.message).toBe("Proposal 'nope' not found.");
  });

  it('gives a friendly message for a 500 with no JSON body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Internal Server Error', { status: 500 })));
    const err = await rejection(apiFetch('/chat'));
    expect(err.status).toBe(500);
    expect(err.message).toMatch(/server hit an error/i);
  });

  it('reports an unreachable server as a network error naming the URL', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const err = await rejection(apiFetch('/daos'));
    expect(err.kind).toBe('network');
    expect(err.message).toMatch(/Cannot reach the API at http/);
  });

  it('times out', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: RequestInit) => new Promise((_res, rej) => init.signal?.addEventListener('abort', () => rej(new DOMException('Aborted', 'AbortError'))))),
    );
    const pending = rejection(apiFetch('/chat', { timeoutMs: 1000 }));
    await vi.advanceTimersByTimeAsync(1001);
    const err = await pending;
    expect(err.kind).toBe('timeout');
  });

  it('lets a caller cancellation propagate as AbortError (not a network error)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: RequestInit) => new Promise((_res, rej) => init.signal?.addEventListener('abort', () => rej(new DOMException('Aborted', 'AbortError'))))),
    );
    const controller = new AbortController();
    const pending = rejection(apiFetch('/daos', { signal: controller.signal }));
    controller.abort();
    const err = await pending;
    expect(err).toBeInstanceOf(DOMException);
    expect(err.name).toBe('AbortError');
  });

  it('rejects an OK response that is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>', { status: 200 })));
    const err = await rejection(apiFetch('/daos'));
    expect(err.kind).toBe('parse');
  });
});

describe('errorMessage', () => {
  it('handles ApiError, Error and unknown values', () => {
    expect(errorMessage(new ApiError('http', 'boom', 500))).toBe('boom');
    expect(errorMessage(new Error('plain'))).toBe('plain');
    expect(errorMessage(42)).toBe('Something went wrong.');
  });
});
