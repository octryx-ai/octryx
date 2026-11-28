// Throttled: every run event nudges a read, so parallel runs would hammer GET /attention.
// After a failed read the next poll waits longer, so a broken server is not hammered.

export const COMPANION_POLL_MS = 30_000;
export const NUDGE_MIN_GAP_MS = 5_000;
export const SAFETY_POLL_MS = 300_000;
export const ERROR_BACKOFF_MAX_MS = 300_000;

export type Clock = {
  now: () => number;
  setTimeout: (run: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
};

export const realClock: Clock = {
  now: () => Date.now(),
  setTimeout: (run, ms) => setTimeout(run, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export function createThrottle(run: () => void, gapMs = NUDGE_MIN_GAP_MS, clock: Clock = realClock) {
  let last = Number.NEGATIVE_INFINITY;
  let trailing: unknown = null;
  const fire = () => { trailing = null; last = clock.now(); run(); };
  return {
    request() {
      const wait = last + gapMs - clock.now();
      if (wait <= 0 && trailing === null) fire();
      else if (trailing === null) trailing = clock.setTimeout(fire, Math.max(wait, 0));
    },
    cancel() {
      if (trailing !== null) clock.clearTimeout(trailing);
      trailing = null;
    },
  };
}

export function pollDelayMs({ socketOpen, failures, pollMs = COMPANION_POLL_MS }: {
  socketOpen: boolean; failures: number; pollMs?: number;
}): number {
  if (failures > 0) return Math.min(pollMs * 2 ** failures, Math.max(ERROR_BACKOFF_MAX_MS, pollMs));
  return socketOpen ? Math.max(SAFETY_POLL_MS, pollMs) : pollMs;
}
