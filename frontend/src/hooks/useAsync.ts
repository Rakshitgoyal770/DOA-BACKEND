import { useCallback, useEffect, useRef, useState } from 'react';
import { isAbortError } from '../api/client';

export interface AsyncState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  /** Run the request again (shows the loading state). */
  reload: () => void;
}

interface Options {
  /** Keep showing the previous result while a new one loads (search boxes, paging). */
  keepPrevious?: boolean;
  /** When false the request is not made and the state stays idle. */
  enabled?: boolean;
}

/**
 * Run an async request whenever `deps` change; cancel it when they change again or
 * the component unmounts, so a slow old response can never overwrite a newer one.
 */
export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  { keepPrevious = false, enabled = true }: Options = {},
): AsyncState<T> {
  const [state, setState] = useState<{ data: T | null; error: Error | null; loading: boolean }>({
    data: null,
    error: null,
    loading: enabled,
  });
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    const controller = new AbortController();
    setState((s) => ({ data: keepPrevious ? s.data : null, error: null, loading: true }));
    fnRef.current(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ data, error: null, loading: false });
      },
      (error: unknown) => {
        if (controller.signal.aborted || isAbortError(error)) return;
        setState({ data: null, error: error instanceof Error ? error : new Error(String(error)), loading: false });
      },
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
