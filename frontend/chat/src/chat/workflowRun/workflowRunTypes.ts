// Wire shapes of a workflow run and of a run list row, as the server sends them.
import type { PublishProve } from "./publishProveView";
import type { RunPipeline } from "./pipelineAuditModel";
import type { RunRuntimeTarget, RuntimeTargetOption } from "./runtimeTargetModel";
import type { TeamWork } from "./teamworkModel";

// A node compiled from a published fragment names it (key, version, reference); an admin also gets the pin.
export type RunNodeFragment = {
  key: string;
  version: number | null;
  ref: string;
  version_id?: string | null;
  checksum?: string;
};
export type RunNode = { id: string; title: string; kind: string; fragment?: RunNodeFragment };
export type RunLoop = {
  edge_id: string;
  title: string;
  used: number;
  limit: number;
};
export type RunAction = {
  key: string;
  label: string;
  input?: RunActionInput | null;
  tone?: string | null;
};
export type RunActionInput =
  | {
      name: string;
      kind: "number";
      min: number;
      max: number;
      default: number;
      label: string;
    }
  | {
      // A reason (abort / stop) or a new branch name; `required`: the action posts only with a text.
      name: string;
      kind: "text";
      default: string;
      label: string;
      required?: boolean;
      // The server's limit (the product owner's answers: 8000); absent: 500, a branch name 200.
      max_length?: number;
    }
  | {
      // change_runtime: where the run executes, one of the requester's choices (the value is the option key).
      name: string;
      kind: "runtime_target";
      default: string;
      label: string;
      options: RuntimeTargetOption[];
    };
export type RunActionValue = number | string | null | undefined;
export type RunCheck = {
  type: string;
  outcome: string;
  blocking: boolean;
  description: string;
  detail: string;
};
export type RunGate = {
  state?: string;
  results?: RunCheck[];
  passed?: boolean;
} | null;
export type RunWaiting = {
  kind: string;
  title?: string;
  subject?: string;
  payload?: Record<string, unknown> | null;
  payload_hash?: string;
  question?: string;
  since?: string | null;
  /** Why it waits, more precisely than the kind ("model_service_retry": the device turn is retried once). */
  reason?: string | null;
  retry_after?: string | null;
  /** The tool approval the run waits for (awaiting_tool_approval); the run bar links to its detail page. */
  approval_id?: string | null;
} | null;

// The readiness task list (T1. … | proof: tests/…::test_name). `done`: the proof test is in the change (not "green",
// the gates check that); null while the change is unknown.
export type RunTaskStatus = "open" | "in_progress" | "done" | "changes" | "verified";
/** A task of the work item (backend task_status): the status is set by the platform from the proof tests in the change,
 * the phase gates and the review; `note` is the review finding on `changes`. `done` is true for done or verified. */
export type RunTaskItem = {
  id: string;
  text: string;
  proof: string;
  done: boolean | null;
  status?: RunTaskStatus;
  note?: string | null;
  updated_at?: string | null;
};

export type WorkflowRun = {
  id: string;
  task_list?: RunTaskItem[];
  title: string;
  workflow_key: string;
  workflow_title?: string | null;
  workflow_kind: string;
  workflow_version: string;
  // The run's Workspace (run view); the run details ask it whether the run's sessions left a transcript.
  project_id?: string | null;
  status: string;
  waiting_kind: string | null;
  pause_reason: string | null;
  outcome: string | null;
  last_error: string | null;
  current_node: RunNode | null;
  phase_position: { index: number | null; total: number };
  // What the run's sessions spent on models (tokens per ticket visible).
  model_usage?: { calls: number; tokens_in: number; tokens_out: number; cost: number };
  nodes: RunNode[];
  loops: RunLoop[];
  // Teamwork: the coordinator's split as it runs; null before the plan (the box says "split at run time").
  work?: TeamWork | null;
  // Started by a test alert (Automation "Send test alert"): no real incident.
  test_alert?: boolean;
  // An imported sample run (the demo's): real data of a run recorded elsewhere.
  sample?: boolean;
  // A triage's follow-up: routed, no route, or failed to start (with the refusal's code and message).
  routing?: RunRouting | null;
  // Exception: the requester is the pull request's author (the connection's account), so not its reviewer.
  reviewer_notice?: { reason: string; url: string; text: string; link_account?: string } | null;
  // B's documentation phase: the published page and whether Knowledge has it.
  documentation?: {
    url?: string;
    title?: string;
    version?: number | null;
    space_key?: string;
    knowledge?: {
      item_state?: string | null;
      version?: string | number | null;
      page_version?: string | number | null;
      in_knowledge?: boolean;
    } | null;
  } | null;
  publish_prove?: PublishProve | null;
  // The CI pipeline: state, commands and the audit of its last report.
  pipeline?: RunPipeline | null;
  // The spec phase's Spec Studio: present once the draft recorded one.
  spec_studio?: { version: number; open_points: number; frozen: boolean; approved: number } | null;
  // on_open_high continue_with_findings: the review findings the run went on with, high first; [] when none.
  open_findings?: {
    severity: string;
    file: string | null;
    line: number | null;
    summary: string;
    fix: string;
  }[];
  gate: RunGate;
  waiting?: RunWaiting;
  pause?: {
    reason: string;
    detail: string;
    // Why the platform paused it, more precisely than the reason (agent_loop, interrupted_by_restart, …).
    code?: string | null;
    // agent_loop: "repeat" (same call again and again) or "noop" (only printed messages).
    loop_kind?: string | null;
    loop?: RunLoop | null;
    // A recoverable platform-action failure (pause reason action_failed).
    failed_action?: {
      node_id: string;
      action: string | null;
      failure_class: string | null;
      reason: string | null;
      detail: Record<string, unknown>;
    } | null;
  } | null;
  // Why a person stopped the run (abort / stop).
  stop?: { reason: string; via?: string | null; at?: string | null } | null;
  // What the run took over from earlier runs of its Work item (branch, ticket, change plan, pull request).
  adopted?: Record<string, Record<string, unknown>> | null;
  // The failure card of a run paused at a loop limit.
  failure?: {
    findings: string;
    follow_up_issue: string | null;
    ticket_key: string | null;
  } | null;
  work_item: {
    id: string;
    key: string;
    title: string;
    url?: string | null;
    state?: string | null;
  } | null;
  ticket_key: string | null;
  branch: string | null;
  // Where the run executes (chosen at start, switched by the change_runtime action).
  runtime_target?: RunRuntimeTarget | null;
  access: string;
  actions: RunAction[];
  updated_at: string | null;
};

export type RunRow = {
  id: string;
  title: string;
  workflow_key: string;
  workflow_kind: string;
  status: string;
  waiting_kind: string | null;
  /** Why a waiting run waits when it says more than its kind ("spec_approval"). */
  waiting_reason?: string | null;
  pause_reason: string | null;
  outcome: string | null;
  current_node_id?: string | null;
  ticket_key?: string | null;
  session_id?: string | null;
  stop_reason?: string | null;
  updated_at: string | null;
  /** An imported sample run (the demo's): shown with a "Sample run" badge. */
  sample?: boolean;
  /** A triage whose follow-up workflow did not start: shown under the run. */
  follow_up_failed?: { workflow_key?: string | null; code?: string | null; message?: string | null } | null;
};

export type RunRouting = {
  state?: string;
  workflow_key?: string;
  run_id?: string;
  code?: string;
  message?: string;
};

export type StartableWorkflow = { key: string; title: string; kind: string };
