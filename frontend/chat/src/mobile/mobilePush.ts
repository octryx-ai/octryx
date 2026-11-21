// Push notification support: the subscription key and whether this browser can subscribe.

// --- notifications ------------------------------------------------------------------------------------------

/** The VAPID public key (base64url) as the bytes `pushManager.subscribe` wants. */
export function applicationServerKey(
  base64url: string,
): Uint8Array<ArrayBuffer> {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(base64 + "=".repeat((4 - (base64.length % 4)) % 4));
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1)
    bytes[index] = binary.charCodeAt(index);
  return bytes;
}

type PushWindow = {
  PushManager?: unknown;
  Notification?: unknown;
  matchMedia?: (query: string) => { matches: boolean };
};
type PushNavigator = {
  serviceWorker?: unknown;
  userAgent?: string;
  standalone?: boolean;
};

/** "ok", "home-screen" (an iPhone's Safari tab: push needs the Home Screen app) or "unsupported". */
export function pushSupport(
  win: PushWindow,
  nav: PushNavigator,
): "ok" | "home-screen" | "unsupported" {
  if (nav.serviceWorker && win.PushManager && win.Notification) return "ok";
  const ios = /iPhone|iPad|iPod/.test(nav.userAgent ?? "");
  const standalone =
    nav.standalone === true ||
    Boolean(win.matchMedia?.("(display-mode: standalone)").matches);
  return ios && !standalone ? "home-screen" : "unsupported";
}
