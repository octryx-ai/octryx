export type NotificationApi = {
  permission: "default" | "granted" | "denied";
  requestPermission: () => Promise<"default" | "granted" | "denied">;
};

export type BrowserNotificationState = "unsupported" | "default" | "granted" | "denied" | "failed";

export function browserNotificationApi(): NotificationApi | null {
  const api = (globalThis as { Notification?: NotificationApi }).Notification;
  return api && typeof api.requestPermission === "function" ? api : null;
}

export function browserNotificationState(api: NotificationApi | null): BrowserNotificationState {
  if (!api) return "unsupported";
  return api.permission === "granted" || api.permission === "denied" ? api.permission : "default";
}

export function browserNotificationText(state: BrowserNotificationState): string {
  if (state === "granted") return "Browser notifications are on while Octryx is open.";
  if (state === "denied") return "Browser notifications are blocked for this site; allow them in the browser's site settings.";
  if (state === "unsupported") return "This browser does not support notifications.";
  if (state === "failed") return "The browser did not complete the notification request. Nothing was changed; you can try again.";
  return "Get a browser notification when an agent needs your decision (only while Octryx is open).";
}

/** Only ever called from a click handler: permission is never asked on page load. */
export async function requestBrowserNotifications(api: NotificationApi | null): Promise<BrowserNotificationState> {
  if (!api) return "unsupported";
  try {
    const result = await api.requestPermission();
    return browserNotificationState({ ...api, permission: result });
  } catch {
    return "failed";
  }
}

type ShownNotification = { onclick: ((event?: unknown) => void) | null; close?: () => void };
type NotificationConstructor = new (title: string, options?: { tag?: string }) => ShownNotification;

/** No `body` option, so a board message body can never reach the operating system. */
export function showBrowserNotification(api: NotificationApi | null, title: string, tag: string, onClick: () => void): boolean {
  if (!api || api.permission !== "granted" || typeof api !== "function") return false;
  try {
    const shown = new (api as unknown as NotificationConstructor)(title, { tag });
    shown.onclick = () => {
      (globalThis as { focus?: () => void }).focus?.();
      onClick();
      shown.close?.();
    };
    return true;
  } catch {
    // Some browsers allow notifications only from a service worker; the bell still shows the item.
    return false;
  }
}

// Default on: granting the browser permission is the opt-in.
const TOGGLE_PREFIX = "octryx-agent-board-notify";

export function readNotifyToggle(userId: string): boolean {
  if (!userId) return true;
  try {
    return window.localStorage.getItem(`${TOGGLE_PREFIX}:${userId}`) !== "off";
  } catch {
    return true;
  }
}

export function storeNotifyToggle(userId: string, on: boolean) {
  if (!userId) return;
  try {
    window.localStorage.setItem(`${TOGGLE_PREFIX}:${userId}`, on ? "on" : "off");
  } catch {
    // Without storage the choice lasts for this page only.
  }
}
