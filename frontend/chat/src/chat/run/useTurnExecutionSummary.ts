import { useCallback, useEffect, useRef, useState } from "react";

import { fetchTurnExecutionSummary } from "./turnExecutionSummaryClient";
import {
  shouldRefreshTurnExecutionSummary,
  subscribeTurnExecutionRefresh,
} from "./turnExecutionRefreshSignal";
import type { TurnExecutionSummaryLoad } from "./turnExecutionSummary.types";

// Coalesces bursts of stream events into one GET per mounted card.
const REFRESH_COALESCE_MS = 250;
// A summary that has not arrived by then ends as "Status not available" with "Try again" (no
// placeholder stays on screen).
export const SUMMARY_GIVE_UP_MS = 30_000;

// Per-turn loader. State is local to the owning message, so a failure only
// affects that message's card. The timeline is virtualized, which keeps the
// fetch lazy: only mounted (visible) assistant turns request their summary.
export function useTurnExecutionSummary(traceId: string | null | undefined) {
  const [load, setLoad] = useState<TurnExecutionSummaryLoad>({
    status: "idle",
  });
  const [attempt, setAttempt] = useState(0);
  const [refreshTick, setRefreshTick] = useState(0);
  const loadRef = useRef(load);
  const traceIdRef = useRef(traceId);

  useEffect(() => {
    loadRef.current = load;
  }, [load]);

  useEffect(() => {
    traceIdRef.current = traceId;
  }, [traceId]);

  useEffect(() => {
    if (!traceId) {
      setLoad({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    let gaveUp = false;
    setLoad({ status: "loading" });
    const giveUp = typeof setTimeout === "function"
      ? setTimeout(() => {
          gaveUp = true;
          controller.abort();
          setLoad({ status: "error" });
        }, SUMMARY_GIVE_UP_MS)
      : undefined;
    const settle = (next: TurnExecutionSummaryLoad) => {
      if (giveUp !== undefined) clearTimeout(giveUp);
      if (!controller.signal.aborted) setLoad(next);
    };
    fetchTurnExecutionSummary(traceId, controller.signal)
      .then(settle)
      .catch(() => settle({ status: "error" }));
    return () => {
      if (giveUp !== undefined) clearTimeout(giveUp);
      if (!gaveUp) controller.abort();
    };
  }, [traceId, attempt]);

  useEffect(() => {
    if (!traceId) {
      return;
    }
    let timer: number | undefined;
    const unsubscribe = subscribeTurnExecutionRefresh(({ sessionId }) => {
      if (!shouldRefreshTurnExecutionSummary(loadRef.current, sessionId)) {
        return;
      }
      window.clearTimeout(timer);
      timer = window.setTimeout(
        () => setRefreshTick((value) => value + 1),
        REFRESH_COALESCE_MS,
      );
    });
    return () => {
      unsubscribe();
      window.clearTimeout(timer);
    };
  }, [traceId]);

  // Silent refetch: the card keeps its last server state while the GET runs,
  // and a transient failure never replaces a known state with an error.
  useEffect(() => {
    const requestedTraceId = traceIdRef.current;
    if (refreshTick === 0 || !requestedTraceId) {
      return;
    }
    const controller = new AbortController();
    fetchTurnExecutionSummary(requestedTraceId, controller.signal)
      .then((result) => {
        if (
          !controller.signal.aborted &&
          traceIdRef.current === requestedTraceId &&
          result.status === "ready"
        ) {
          setLoad(result);
        }
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [refreshTick]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  return { load, retry };
}
