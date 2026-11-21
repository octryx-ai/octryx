import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import type { NotificationApi } from "../agents/browserNotifications";
import { connectAttentionSocket, readAttention, sendWatch, startAttentionPolling, type Watched } from "./companionConnection";
import { COMPANION_POLL_MS } from "./companionReload";
import { type Attention, type AttentionItem } from "./companionTypes";
import { createThrottle, NUDGE_MIN_GAP_MS } from "./companionReload";

export type CompanionState = {
  attention: Attention | null;
  problem: string | null;
  reload: () => void;
  /** Takes an answered or dismissed item out at once; the next load confirms it. */
  remove: (key: string) => void;
  /**
   * Watches one run over the attention socket ({"watch": run_id}); `onChange` runs on each job_changed nudge for it.
   * null (or another run) sends {"unwatch": run_id} for the previous run; later nudges for it are ignored anyway.
   */
  watchJob: (runId: string | null, onChange?: () => void) => void;
};

/**
 * Loads the attention list, reloads on a WebSocket nudge ({type: "attention_changed"}, or job_changed without a run) over the
 * session cookie, every 30 s and when the window gets focus (the fallback when the socket is missing or drops), and
 * raises a browser notification for new items that notify (title only, never a body).
 */
export function useCompanion({ userId, notificationApi, onOpenItem, pollMs = COMPANION_POLL_MS, socket = true }: {
  userId: string;
  notificationApi: NotificationApi | null;
  onOpenItem: (item: AttentionItem) => void;
  pollMs?: number;
  socket?: boolean;
}): CompanionState {
  const [attention, setAttention] = useState<Attention | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const seen = useRef<Set<string> | null>(null);
  const latest = useRef({ userId, notificationApi, onOpenItem });
  latest.current = { userId, notificationApi, onOpenItem };
  const generation = useRef(0);
  const socketRef = useRef<WebSocket | null>(null);
  const watched = useRef<Watched | null>(null);

  const failures = useRef(0);
  const socketOpen = useRef(false);
  const stale = useRef(false);

  const readNow = useCallback(() => {
    readAttention({ generation, failures, seen, latest, setProblem, setAttention });
  }, []);

  // Every trigger (socket nudge, focus, poll, the tab becoming visible) reads through one throttle; a hidden tab
  // only remembers that it is behind and reads once when it is shown again.
  const throttle = useMemo(() => createThrottle(readNow, NUDGE_MIN_GAP_MS), [readNow]);
  useEffect(() => () => throttle.cancel(), [throttle]);
  const reload = useCallback(() => {
    if (typeof document !== "undefined" && document.hidden) { stale.current = true; return; }
    throttle.request();
  }, [throttle]);

  const remove = useCallback((key: string) => {
    setAttention((current) => current && { ...current, items: current.items.filter((item) => item.key !== key) });
  }, []);

  useEffect(
    () => startAttentionPolling({ reload, readNow, pollMs, generation, socketOpen, failures, stale }),
    [pollMs, reload, readNow],
  );

  const watchJob = useCallback((runId: string | null, onChange?: () => void) => {
    sendWatch(watched, socketRef, runId, onChange);
  }, []);

  useEffect(() => {
    if (!socket || typeof WebSocket === "undefined") return;
    return connectAttentionSocket({ reload, socketRef, socketOpen, watched });
  }, [reload, socket]);

  return { attention, problem, reload, remove, watchJob };
}
