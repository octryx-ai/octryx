import type { ThreadSummary } from "../chatThreadTypes";

export function getThreadSignalKind(thread: ThreadSummary) {
  const runStatus = String(thread.runStatus || "")
    .trim()
    .toLowerCase();
  const runReason = String(thread.runCompletionReason || "")
    .trim()
    .toLowerCase();
  if (runStatus === "in_progress") {
    return "running";
  }
  if (runStatus === "awaiting_approval") {
    return "attention";
  }
  if (runReason === "human_input_required") {
    return "attention";
  }
  if (runStatus === "failed") {
    return "error";
  }
  // A thread whose newest turn was stopped by a check is never shown as done.
  if (thread.latestTurnStopped === true) {
    return "turn-stopped";
  }
  if (runStatus === "stopped") {
    return "stopped";
  }
  if (runStatus === "completed") {
    return "done";
  }
  if (thread.status === "running") {
    return "running";
  }
  if (thread.status === "error") {
    return "error";
  }
  if (thread.status === "pending_approval") {
    return "attention";
  }
  if (thread.stopReason === "user_cancelled") {
    return "stopped";
  }
  if (thread.status === "archived") {
    return "stopped";
  }
  return "done";
}

/** This list is also the legend; `done` and `stopped` carry no marker. */
export const THREAD_MARKERS = [
  { kind: "running", label: "Running", hint: "A turn is in progress." },
  { kind: "attention", label: "Needs you", hint: "Waiting for your approval or answer." },
  { kind: "turn-stopped", label: "Stopped by a check", hint: "A safety or quality check stopped the last turn." },
  { kind: "error", label: "Failed", hint: "The last turn failed." },
] as const;

export const UNMARKED_THREAD_SIGNALS = ["done", "stopped"] as const;

export type ThreadMarkerKind = (typeof THREAD_MARKERS)[number]["kind"];

export function threadMarkerKind(kind: string): ThreadMarkerKind | null {
  return THREAD_MARKERS.some((marker) => marker.kind === kind) ? (kind as ThreadMarkerKind) : null;
}

/** Accessible label of a row marker; null where the row shows no marker. */
// An unknown or missing stop reason never gets a guessed cause.
const STOP_CAUSE: Record<string, string> = {
  agent_reply_not_json: "reply format not met",
  agent_reply_schema_mismatch: "reply format not met",
  agent_reply_contract_invalid: "reply format not valid",
  answer_evidence_uncited: "evidence check",
  answer_evidence_invented_url: "evidence check",
  step_tool_required: "step check",
  step_stalled: "step check",
};

export function threadSignalLabel(
  kind: string,
  stopReason?: unknown,
): string | null {
  if (kind !== "turn-stopped") {
    return THREAD_MARKERS.find((marker) => marker.kind === kind)?.label ?? null;
  }
  const cause =
    typeof stopReason === "string" &&
    Object.prototype.hasOwnProperty.call(STOP_CAUSE, stopReason)
      ? STOP_CAUSE[stopReason]
      : null;
  return cause
    ? `Last turn stopped: ${cause}`
    : "Last turn stopped by a safety or quality check";
}
