// React state is read from the render closure, so a second Enter before the re-render would pass; the ref is claimed synchronously.
// A failed send keeps its idempotency key, so a retry never starts a second turn.

export type SendGuard = {
  inFlight: boolean;
  draftKey: string | null;
};

export function createSendGuard(): SendGuard {
  return { inFlight: false, draftKey: null };
}

export function claimSend(guard: SendGuard): boolean {
  if (guard.inFlight) {
    return false;
  }
  guard.inFlight = true;
  return true;
}

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

export function draftSendKey(guard: SendGuard, makeKey: () => string = randomKey): string {
  if (!guard.draftKey) {
    guard.draftKey = makeKey();
  }
  return guard.draftKey;
}
