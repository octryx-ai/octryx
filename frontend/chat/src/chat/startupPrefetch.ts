// Started before the bootstrap since these need nothing from it; a later reader, or one after MAX_AGE_MS, reads anew.
const MAX_AGE_MS = 15_000;

const entries = new Map<string, { promise: Promise<unknown>; at: number }>();

export function prefetch<T>(url: string, read: () => Promise<T>): void {
  if (entries.has(url)) return;
  const promise = read();
  // An untaken refusal must not surface as an unhandled rejection.
  promise.catch(() => undefined);
  entries.set(url, { promise, at: Date.now() });
}

export function takePrefetched<T>(url: string): Promise<T> | null {
  const entry = entries.get(url);
  if (!entry) return null;
  entries.delete(url);
  return Date.now() - entry.at <= MAX_AGE_MS ? (entry.promise as Promise<T>) : null;
}
