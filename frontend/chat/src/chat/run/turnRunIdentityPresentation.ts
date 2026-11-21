// Pure presentation of a turn's Run/Attempt identity. The status palette is
// used for the attempt state. Only `completed` gets the success tone, sage
// green (status-active, a status colour only); a finished, unverified attempt
// stays neutral.

import type { ClosedValue } from "./turnExecutionSummary.types";
import type { TurnRunEndReason, TurnRunIdentityKind, TurnRunState } from "./turnRunIdentityParse";

export type TurnRunTone =
  | "success"
  | "neutral"
  | "running"
  | "attention"
  | "blocked"
  | "error";

const KIND_LABELS: Record<TurnRunIdentityKind, string> = {
  product_run: "Product run",
  unscoped_turn: "No run (session has no Workspace)",
  compat_turn: "No run recorded",
  unresolved: "Run not resolvable",
};

export function presentRunIdentityKind(kind: TurnRunIdentityKind) {
  return KIND_LABELS[kind];
}

const STATE_PRESENTATION: Record<TurnRunState, [TurnRunTone, string]> = {
  requested: ["running", "Requested"],
  admitted: ["running", "Admitted"],
  running: ["running", "Running"],
  completed: ["success", "Completed"],
  finished_unverified: ["neutral", "Finished, unverified"],
  failed: ["error", "Failed"],
  cancelled: ["neutral", "Cancelled"],
  denied: ["blocked", "Denied"],
  needs_approval: ["attention", "Needs approval"],
  needs_configuration: ["attention", "Needs configuration"],
  needs_clarification: ["attention", "Needs clarification"],
  waiting_approval: ["attention", "Waiting for approval"],
  incomplete: ["attention", "Incomplete"],
  unknown: ["neutral", "Unknown"],
};

export function presentRunState(state: ClosedValue<TurnRunState> | unknown) {
  if (
    typeof state === "string" &&
    Object.prototype.hasOwnProperty.call(STATE_PRESENTATION, state)
  ) {
    const [tone, label] = STATE_PRESENTATION[state as TurnRunState];
    return { tone, label };
  }
  return { tone: "neutral" as TurnRunTone, label: "Unrecognized" };
}

export function presentEndReason(reason: ClosedValue<string> | null) {
  if (reason === null) {
    return null;
  }
  return typeof reason === "string" ? reason : "unrecognized";
}

// Readable end reasons; the raw code stays under "Technical details".
const END_REASON_LABELS: Record<TurnRunEndReason, string> = {
  gate_denied: "Not allowed by the execution profile",
  gate_missing_profile: "No execution profile",
  gate_unknown_status: "Execution profile status unknown",
  gate_needs_approval: "Needs approval",
  gate_needs_configuration: "Needs configuration",
  gate_needs_clarification: "Needs clarification",
  runtime_not_ready: "Runtime not ready",
  model_alias_not_admitted: "Model not admitted",
  model_data_policy_denied: "Blocked by the model data policy",
  preparation_failed: "Preparation failed",
  runtime_finished: "Reply delivered",
  provider_error: "Model provider error",
  runtime_error: "Runtime error",
  runtime_exception: "Unexpected runtime error",
  approval_pending: "Waiting for approval",
  clarification_requested: "Clarification requested",
  completion_not_accepted: "Result not accepted",
  delegated_outcome_unrecorded: "Delegated result not recorded",
  generator_closed: "Stream closed",
  task_cancelled: "Cancelled",
  interrupted_by_restart: "Interrupted by a restart",
  awaiting_workflow_confirmation: "Waiting for workflow confirmation",
  unknown: "Unknown",
};

export function presentEndReasonLabel(reason: ClosedValue<string> | null) {
  if (reason === null) {
    return null;
  }
  return typeof reason === "string" &&
    Object.prototype.hasOwnProperty.call(END_REASON_LABELS, reason)
    ? END_REASON_LABELS[reason as TurnRunEndReason]
    : "Unrecognized";
}

// An open profile vocabulary value (`direct_chat_safe`, `chat_default`) as words: "Direct chat safe".
export function readableCode(value: string | null | undefined) {
  if (!value) {
    return null;
  }
  const words = value.replace(/[._-]+/g, " ").replace(/\s+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : null;
}

export function shortRunId(id: string) {
  return id.slice(0, 8);
}
