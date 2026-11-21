// One send at a time, one key per draft message.
//
// React state (`sending`) is read from the render closure, so a second Enter before the re-render
// passed the old guard and opened a second thread. The guard is a plain object held in a ref and
// claimed synchronously. Each draft message gets one `idempotency_key`; a failed send keeps it, so
// the retry (or a request that reached the server after all) never starts a second turn.

export type SendGuard = {
  inFlight: boolean;
  draftKey: string | null;
};

export function createSendGuard(): SendGuard {
  return { inFlight: false, draftKey: null };
}

/** False when a send is already in flight; otherwise claims the guard. */
export function claimSend(guard: SendGuard): boolean {
  if (guard.inFlight) {
    return false;
  }
  guard.inFlight = true;
  return true;
}

/** Releases the guard; a delivered message frees its key for the next draft. */
export function releaseSend(guard: SendGuard, { delivered }: { delivered: boolean }) {
  guard.inFlight = false;
  if (delivered) {
    guard.draftKey = null;
  }
}

function randomKey() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `send-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/** The current draft message's key, created on first use. */
export function draftSendKey(guard: SendGuard, makeKey: () => string = randomKey): string {
  if (!guard.draftKey) {
    guard.draftKey = makeKey();
  }
  return guard.draftKey;
}
