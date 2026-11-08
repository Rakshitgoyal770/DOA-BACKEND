/**
 * HTTP client for the backend: one place that builds URLs, applies timeouts,
 * and turns every failure into an ApiError with a message a person can act on.
 *
 * FastAPI error bodies come in two shapes, both handled here:
 *   {"detail": "Proposal 'x' not found."}                    (HTTPException)
 *   {"detail": [{"loc": ["body","query"], "msg": "..."}]}     (422 validation)
 */
import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '../config';

export type ApiErrorKind = 'network' | 'timeout' | 'http' | 'parse';

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;

  constructor(kind: ApiErrorKind, message: string, status: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: 'GET' | 'POST';
  query?: Query;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export function buildUrl(path: string, query?: Query): string {
  const url = new URL(`${API_BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** Pull a readable message out of a FastAPI error body. */
export function detailFromBody(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((d) => {
          if (d && typeof d === 'object' && 'msg' in d) {
            const loc = Array.isArray((d as { loc?: unknown[] }).loc)
              ? (d as { loc: unknown[] }).loc.filter((p) => p !== 'body' && p !== 'query').join('.')
              : '';
            return loc ? `${loc}: ${(d as { msg: string }).msg}` : (d as { msg: string }).msg;
          }
          return null;
        })
        .filter(Boolean);
      if (messages.length) return messages.join('; ');
    }
  }
  return fallback;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, body, signal, timeoutMs = REQUEST_TIMEOUT_MS } = options;

  // One controller merges the caller's cancellation with our timeout.
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onCallerAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', onCallerAbort, { once: true });
  }

  try {
    let response: Response;
    try {
      response = await fetch(buildUrl(path, query), {
        method,
        headers: body !== undefined ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      if (timedOut) {
        throw new ApiError('timeout', `The server did not answer within ${Math.round(timeoutMs / 1000)} seconds.`);
      }
      if (signal?.aborted) throw err; // caller cancelled: let AbortError propagate
      throw new ApiError('network', `Cannot reach the API at ${API_BASE_URL}. Is the backend running?`);
    }

    let payload: unknown = null;
    const text = await response.text();
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        if (response.ok) throw new ApiError('parse', 'The server returned a response that is not valid JSON.', response.status);
      }
    }

    if (!response.ok) {
      const fallback =
        response.status >= 500 ? 'The server hit an error while handling this request.' : `Request failed (${response.status}).`;
      throw new ApiError('http', detailFromBody(payload, fallback), response.status);
    }
    return payload as T;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onCallerAbort);
  }
}

/**
 * True when the server does not have the endpoint at all: FastAPI answers an unknown route
 * with {"detail": "Not Found"}, while an unknown proposal gets "Proposal '...' not found."
 * So this means "the backend is older than this frontend", not "this item is missing".
 */
export function isMissingEndpoint(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404 && err.message === 'Not Found';
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError';
}

/** Message for any thrown value, for display. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong.';
}
