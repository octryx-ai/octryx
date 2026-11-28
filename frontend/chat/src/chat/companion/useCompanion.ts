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
  remove: (key: string) => void;
  watchJob: (runId: string | null, onChange?: () => void) => void;
};

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

  // A hidden tab only remembers that it is behind and reads once when it is shown again.
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
