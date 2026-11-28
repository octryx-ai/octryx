// Status, waiting and pause labels of a workflow run and its badge tone.
import type { RunWaiting, WorkflowRun, RunRow } from "./workflowRunTypes";

export type BadgeTone =
  | "active"
  | "running"
  | "attention"
  | "danger"
  | "neutral";

const STATUS_LABELS: Record<string, string> = {
  running: "Running",
  waiting: "Waiting",
  paused: "Paused",
  completed: "Completed",
  stopped: "Stopped",
  failed: "Failed",
};

const WAITING_LABELS: Record<string, string> = {
  waiting_for_reply: "Waiting for your reply",
  awaiting_confirmation: "Waiting for your confirmation",
  awaiting_approval: "Waiting for an approval",
  watching: "Waiting for an external state",
  sub_workflow: "Waiting for a sub-workflow",
  awaiting_tool_approval: "Waiting for you to allow the next step",
  awaiting_review: "The independent reviewer reviews the change",
  waiting_for_device: "Waiting for the device",
  awaiting_device: "Waiting for the device",
  functional_acceptance: "Waiting for functional acceptance",
  audience_receipt: "Waiting for the audience to check access",
};

export const EMERGENCY_STOP = "emergency_stop";

const PAUSE_LABELS: Record<string, string> = {
  loop_limit: "A loop reached its limit",
  checks_failed: "The checks stayed red",
  needs_approval: "A change needs your approval",
  budget_limit: "The run budget is used up",
  no_reply: "No reply in time",
  watch_timeout: "The watched state did not arrive in time",
  approval_timeout: "The approval did not arrive in time",
  review_no_decision: "The independent review gave no verdict",
  action_failed: "A step failed — retry, change or abort",
  environment_not_ready: "The tests cannot run here yet — fix the environment, then retry",
  workspace_dirty: "The working folder has uncommitted changes — commit or stash, then retry",
  evidence_unresolved: "The platform could not match the test evidence — fix it, then re-check",
  needs_configuration: "Publication configuration is missing",
  publish_unverified: "Publication is unverified — reconcile before another send",
  audience_unproven: "Audience access is unproven",
  acceptance_timeout: "Functional acceptance is still pending",
  documentation_missing: "Documentation is missing",
  content_blocked: "A content policy refused the agent turn's content — review it, then continue or abort",
  runtime_failed: "The agent turn failed in the runtime — continue to run the phase again, or abort",
  // Operations › Live emergency stop: an admin paused it; Continue resumes it.
  emergency_stop: "Stopped by emergency stop",
  // A detected loop pauses the run itself; Continue resumes it.
  loop_detected: "Loop detected · paused automatically",
  // The step needs a person's own subscription seat, which no server runner holds.
  seat_required: "Needs a person's seat",
};

// runtime_failed covers very different causes; its code names the one that happened (a loop
// stop must not read like a crash). Matched in order, the first prefix wins.
const PAUSE_CODE_LABELS: Array<[string, string]> = [
  ["emergency_stop", "Stopped by emergency stop"],
  ["loop_detected", "Loop detected · paused automatically"],
  ["agent_loop:noop", "The agent only printed messages instead of working — stopped to save tokens"],
  ["agent_loop", "The agent repeated the same step — stopped to save tokens"],
  ["interrupted_by_restart", "The server restarted during this phase — continue to pick it up again"],
  ["server_turn_refused_", "The platform could not start this phase's turn — continue to try again"],
  ["server_turn_failed", "The model call failed in this phase — continue to run it again"],
  ["device_turn_usage_limit", "The Claude account on the device reached its usage limit"],
  ["device_approvals_unanswered", "Approvals on the device were not answered"],
  ["device_turn_", "The device ended the phase without finishing it"],
  ["phase_not_finished", "The phase ended without finishing its work"],
  ["phase_stalled", "The phase made no progress"],
  ["fixture_problem", "Test fixture: the phase ended without finishing it"],
  ["no_seat_device_online", "Needs a person's seat · no device with one online"],
];

type PauseFacts = { code?: string | null; loop_kind?: string | null } | null | undefined;

export function pauseTitle(reason: string, pause?: PauseFacts): string {
  const code = String(pause?.code ?? "");
  if (code) {
    const key = pause?.loop_kind ? `${code}:${pause.loop_kind}` : code;
    const hit = PAUSE_CODE_LABELS.find(([prefix]) => key.startsWith(prefix));
    if (hit) return hit[1];
  }
  return PAUSE_LABELS[reason] ?? reason;
}

// Waits whose reason says more than their kind (a model service error on the device is retried
// once, ~20 s later; the run only pauses when the retry fails too).
const WAITING_REASON_LABELS: Record<string, string> = {
  model_service_retry: "Retrying after a model service error",
  // spec-writing's decisions gate waits for the product owner in the Spec Studio (backend product_owner_wait.py).
  spec_approval: "Waiting for spec approval",
  product_owner_approval: "Waiting for the product owner",
};

export function runStatusLabel(
  run: Pick<
    WorkflowRun,
    "status" | "waiting_kind" | "pause_reason" | "outcome"
  > & { pause?: PauseFacts; waiting?: RunWaiting; waiting_reason?: string | null },
): string {
  const reason = String(run.waiting?.reason ?? run.waiting_reason ?? "");
  const reasonLabel = run.status === "waiting" ? WAITING_REASON_LABELS[reason] : undefined;
  if (reasonLabel) return reasonLabel;
  if (run.status === "waiting" && run.waiting_kind)
    return WAITING_LABELS[run.waiting_kind] ?? STATUS_LABELS.waiting;
  // An emergency stop says so on its own, not "Paused · …".
  if (run.status === "paused" && run.pause_reason === EMERGENCY_STOP) return PAUSE_LABELS[EMERGENCY_STOP];
  if (run.status === "paused" && run.pause_reason)
    return `Paused · ${pauseTitle(run.pause_reason, run.pause)}`;
  if (run.status === "completed" && run.outcome)
    return `Completed · ${run.outcome}`;
  return STATUS_LABELS[run.status] ?? run.status;
}

export function runStatusTone(status: string): BadgeTone {
  if (status === "running") return "running";
  if (status === "waiting" || status === "paused") return "attention";
  if (status === "failed") return "danger";
  if (status === "completed") return "active";
  return "neutral";
}

// A paused run is a run flag on the Work item, never a Work state.
export function runFlagText(
  row: Pick<RunRow, "status" | "pause_reason" | "waiting_kind">,
): string | null {
  if (row.status === "paused") return "Run paused";
  if (row.status === "waiting") return "Run waiting";
  return null;
}

// Observability → Runs → Workflow runs: the status filter, with "needs a decision" (paused or waiting) first.
export const RUN_STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: "attention", label: "Needs a decision" },
  { value: "paused", label: "Paused" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "stopped", label: "Stopped" },
  { value: "failed", label: "Failed" },
  { value: "", label: "All" },
];
