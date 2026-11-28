// A new chat's draft key changes while it boots, so the prefill is keyed by Workspace and stays readable for two minutes.
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
