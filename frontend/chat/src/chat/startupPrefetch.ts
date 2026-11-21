// Requests the app starts as soon as its bundle runs, in parallel with the chat bootstrap (perf audit
// login: the companion's attention list and the admin's setup progress waited for the bootstrap although they need
// nothing from it). The first reader of the same URL takes the answer; a later reader, or one after MAX_AGE_MS,
// reads anew, so nothing stale is shown.
const MAX_AGE_MS = 15_000;

const entries = new Map<string, { promise: Promise<unknown>; at: number }>();

export function prefetch<T>(url: string, read: () => Promise<T>): void {
  if (entries.has(url)) return;
  const promise = read();
  // A refusal reaches the reader that takes it; an untaken one must not surface as an unhandled rejection.
  promise.catch(() => undefined);
  entries.set(url, { promise, at: Date.now() });
}

export function takePrefetched<T>(url: string): Promise<T> | null {
  const entry = entries.get(url);
  if (!entry) return null;
  entries.delete(url);
  return Date.now() - entry.at <= MAX_AGE_MS ? (entry.promise as Promise<T>) : null;
}
