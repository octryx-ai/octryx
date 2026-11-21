// The moving parts behind useCompanion: one attention read, the poll and window triggers, the watch messages and the
// attention socket with its reconnect backoff. Plain functions over the hook's refs and setters.
import type { MutableRefObject } from "react";

import { ACTION_NEEDED_REFRESH_EVENT } from "../agents/actionNeededRefresh";
import { readNotifyToggle, showBrowserNotification, type NotificationApi } from "../agents/browserNotifications";
import { attentionSocketUrl, loadAttention } from "./companionApi";
import { unwatchMessage } from "./companionHandoverModel";
import { watchMessage } from "./companionJobModel";
import { itemsToNotify } from "./companionModel";
import { type Attention, type AttentionItem } from "./companionTypes";
import { pollDelayMs } from "./companionReload";

export type Watched = { runId: string; onChange: () => void };
type Ref<T> = MutableRefObject<T>;
type Latest = { userId: string; notificationApi: NotificationApi | null; onOpenItem: (item: AttentionItem) => void };

export function readAttention({ generation, failures, seen, latest, setProblem, setAttention }: {
  generation: Ref<number>;
  failures: Ref<number>;
  seen: Ref<Set<string> | null>;
  latest: Ref<Latest>;
  setProblem: (problem: string | null) => void;
  setAttention: (attention: Attention) => void;
}) {
  const run = ++generation.current;
  loadAttention().then((next) => {
    if (run !== generation.current) return;
    failures.current = 0;
    setProblem(null);
    setAttention(next);
    const { userId: viewer, notificationApi: api, onOpenItem: open } = latest.current;
    if (readNotifyToggle(viewer)) {
      for (const item of itemsToNotify(seen.current, next)) showBrowserNotification(api, item.title, item.key, () => open(item));
    }
    seen.current = new Set(next.items.map((item) => item.key));
  }).catch(() => {
    if (run !== generation.current) return;
    failures.current += 1;
    setProblem("What needs you could not be loaded.");
  });
}

/** Starts the poll and the focus, refresh-event and visibility triggers; returns the cleanup. */
export function startAttentionPolling({ reload, readNow, pollMs, generation, socketOpen, failures, stale }: {
  reload: () => void;
  readNow: () => void;
  pollMs: number;
  generation: Ref<number>;
  socketOpen: Ref<boolean>;
  failures: Ref<number>;
  stale: Ref<boolean>;
}) {
  const loads = generation;
  let timer: ReturnType<typeof setTimeout> | null = null;
  // The poll is the fallback while the socket is not open, a slow safety net while it is, and backs off on errors.
  const tick = () => {
    reload();
    timer = setTimeout(tick, pollDelayMs({ socketOpen: socketOpen.current, failures: failures.current, pollMs }));
  };
  const shown = () => {
    if (typeof document !== "undefined" && !document.hidden && stale.current) { stale.current = false; reload(); }
  };
  readNow();
  timer = setTimeout(tick, pollDelayMs({ socketOpen: socketOpen.current, failures: 0, pollMs }));
  window.addEventListener("focus", reload);
  window.addEventListener(ACTION_NEEDED_REFRESH_EVENT, reload);
  if (typeof document !== "undefined") document.addEventListener("visibilitychange", shown);
  return () => {
    // An answer that arrives after unmount is ignored.
    loads.current++;
    if (timer) clearTimeout(timer);
    window.removeEventListener("focus", reload);
    window.removeEventListener(ACTION_NEEDED_REFRESH_EVENT, reload);
    if (typeof document !== "undefined") document.removeEventListener("visibilitychange", shown);
  };
}

export function sendWatch(watched: Ref<Watched | null>, socketRef: Ref<WebSocket | null>, runId: string | null, onChange?: () => void) {
  const previous = watched.current?.runId ?? null;
  watched.current = runId && onChange ? { runId, onChange } : null;
  const ws = socketRef.current;
  if (!ws || ws.readyState !== 1) return;
  try {
    if (previous && previous !== runId) ws.send(unwatchMessage(previous));
    if (runId && runId !== previous) ws.send(watchMessage(runId));
  } catch { /* the next open sends the watch again */ }
}

function onSocketMessage(event: MessageEvent, watched: Ref<Watched | null>, reload: () => void) {
  try {
    const message = JSON.parse(String(event.data));
    if (message?.type === "job_changed" && message.run_id) {
      const current = watched.current;
      if (current && current.runId === message.run_id) current.onChange();
    } else if (message?.type === "attention_changed" || message?.type === "job_changed") reload();
  } catch {
    // Not a nudge; polling still covers it.
  }
}

/** Opens the attention socket and reconnects with backoff until the returned cleanup runs. */
export function connectAttentionSocket({ reload, socketRef, socketOpen, watched }: {
  reload: () => void;
  socketRef: Ref<WebSocket | null>;
  socketOpen: Ref<boolean>;
  watched: Ref<Watched | null>;
}) {
  let closed = false;
  let ws: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let delay = 2_000;
  const connect = () => {
    try {
      ws = new WebSocket(attentionSocketUrl(window.location));
    } catch {
      return;
    }
    socketRef.current = ws;
    ws.onopen = () => {
      delay = 2_000;
      socketOpen.current = true;
      // A watch does not survive a reconnect on the server, so it is sent again.
      if (watched.current) ws?.send(watchMessage(watched.current.runId));
    };
    ws.onmessage = (event) => onSocketMessage(event, watched, reload);
    ws.onclose = () => {
      socketRef.current = null;
      socketOpen.current = false;
      if (closed) return;
      // Backoff up to 5 minutes; polling keeps the list current meanwhile.
      retry = setTimeout(connect, delay);
      delay = Math.min(delay * 2, 300_000);
    };
  };
  connect();
  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    ws?.close();
  };
}
