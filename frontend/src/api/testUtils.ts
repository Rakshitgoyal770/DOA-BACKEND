/** Test helper: the error a promise rejects with, typed. Fails the test if the promise resolves. */
export function rejection<E = Error & { status?: number | null; kind?: string; isNotFound?: boolean }>(promise: Promise<unknown>): Promise<E> {
  return promise.then(
    () => {
      throw new Error('Expected the promise to reject, but it resolved.');
    },
    (error: unknown) => error as E,
  );
}
