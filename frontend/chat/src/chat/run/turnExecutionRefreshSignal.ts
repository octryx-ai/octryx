import type { TurnExecutionSummaryLoad } from "./turnExecutionSummary.types";

// Narrow browser signal: approval or run state changed for a session. It is
// emitted by the session stream owner and the local approval decision
// handler. Listeners may only re-issue their own read-only summary GET.
export const TURN_EXECUTION_REFRESH_EVENT = "octryx:turn-execution-refresh";

export type TurnExecutionRefreshDetail = { sessionId: string };

export function emitTurnExecutionRefresh(
  sessionId: string,
  target: EventTarget = window,
) {
  target.dispatchEvent(
    new CustomEvent<TurnExecutionRefreshDetail>(TURN_EXECUTION_REFRESH_EVENT, {
      detail: { sessionId },
    }),
  );
}

export function subscribeTurnExecutionRefresh(
  listener: (detail: TurnExecutionRefreshDetail) => void,
  target: EventTarget = window,
): () => void {
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<unknown>).detail as
      | Partial<TurnExecutionRefreshDetail>
      | null
      | undefined;
    if (detail && typeof detail.sessionId === "string" && detail.sessionId) {
      listener({ sessionId: detail.sessionId });
    }
  };
  target.addEventListener(TURN_EXECUTION_REFRESH_EVENT, handler);
  return () =>
    target.removeEventListener(TURN_EXECUTION_REFRESH_EVENT, handler);
}

// A trace is immutable once its turn settled, so only summaries that can still
// change are refetched: a pending approval, an `unknown` state whose reason is
// not fixed for the trace, or a state this client does not recognize. A gate
// `needs_approval` block creates no approval request and cannot change.
// Loading/error/unavailable cards are left to their own load or manual retry.
const FIXED_UNKNOWN_REASONS: ReadonlySet<string> = new Set([
  "intermediate_trace",
  "missing_snapshot",
  "malformed_snapshot",
  "inconsistent_snapshot",
]);

export function shouldRefreshTurnExecutionSummary(
  load: TurnExecutionSummaryLoad,
  sessionId: string,
) {
  if (load.status !== "ready") {
    return false;
  }
  const { summary } = load;
  if (summary.sessionId && summary.sessionId !== sessionId) {
    return false;
  }
  if (typeof summary.state !== "string") {
    return true;
  }
  if (summary.state === "unknown") {
    return !FIXED_UNKNOWN_REASONS.has(summary.stateReason.code ?? "");
  }
  return summary.state === "waiting_approval";
}
