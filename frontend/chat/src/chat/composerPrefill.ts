// A one-shot hand-off of a composer text from another page (Knowledge Search "Ask in chat"). The draft
// key of a new chat changes while the chat boots (runtime target, mode), so a text written under one key could be
// missed; the prefill names the Workspace instead and stays readable for two minutes after it was written.
const KEY = "octryx.composer.prefill.v1";
const TTL_MS = 2 * 60_000;

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function writeComposerPrefill(store: Store | null, projectId: string, text: string, now = Date.now()) {
  try {
    store?.setItem(KEY, JSON.stringify({ projectId, text, at: now }));
  } catch {
    // Without storage the chat opens empty; the question is still on the page it came from.
  }
}

/** Takes the prefill for a new chat in this Workspace while it is fresh (it is removed); otherwise "". */
export function takeComposerPrefill(store: Store | null, projectId: string, now = Date.now()): string {
  try {
    const raw = store?.getItem(KEY);
    if (!raw) return "";
    const value = JSON.parse(raw) as { projectId?: unknown; text?: unknown; at?: unknown };
    const fresh = typeof value.at === "number" && now - value.at <= TTL_MS;
    const mine = value.projectId === projectId && typeof value.text === "string";
    if (!fresh || mine) store?.removeItem(KEY);
    return fresh && mine ? (value.text as string) : "";
  } catch {
    return "";
  }
}
