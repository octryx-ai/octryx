// API paths and request bodies for workflow runs: listing, starting, acting on and limiting them.
import type { RuntimeTargetOption } from "./runtimeTargetModel";
import type { RunAction, RunActionValue, WorkflowRun } from "./workflowRunTypes";

export const WORKFLOW_RUNS_PATH = "/api/v1/workflow-runs";

export function runBySessionPath(sessionId: string): string {
  return `${WORKFLOW_RUNS_PATH}/by-session/${encodeURIComponent(sessionId)}`;
}

// The request an action posts; `input` carries an action's typed value (iterations, a reason, a branch name).
export function runActionRequest(
  run: Pick<WorkflowRun, "id" | "waiting">,
  action: RunAction,
  input?: RunActionValue,
): { path: string; body: Record<string, unknown> } {
  const base = `${WORKFLOW_RUNS_PATH}/${encodeURIComponent(run.id)}`;
  if (action.key === "resume_in_new_session")
    return { path: `${base}/sessions`, body: {} };
  const body: Record<string, unknown> = { action: action.key };
  if (action.input?.kind === "number" && typeof input === "number")
    body[action.input.name] = input;
  if (action.input?.kind === "text" && typeof input === "string" && input.trim())
    body[action.input.name] = input.trim();
  if (action.input?.kind === "runtime_target") {
    const chosen = action.input.options.find((option) => option.key === input);
    if (chosen) body[action.input.name] = chosen.target;
  }
  if (run.waiting?.payload_hash) body.payload_hash = run.waiting.payload_hash;
  return { path: `${base}/actions`, body };
}

// An action whose required text is still empty cannot be posted (the server refuses it as well).
export function actionReady(action: RunAction, input: RunActionValue): boolean {
  if (action.input?.kind !== "text" || !action.input.required) return true;
  return typeof input === "string" && input.trim().length > 0;
}

export function runsForWorkItemPath(workItemId: string): string {
  return `${WORKFLOW_RUNS_PATH}?work_item_id=${encodeURIComponent(workItemId)}`;
}

// With a Work item, the answer also names `entry_workflow`: the workflow its next run starts with (an incident skips
// the triage, spec B/C §1), for the start form to preselect; the person still chooses.
export function startableWorkflowsPath(
  projectId: string | null | undefined,
  workItemId?: string | null,
): string {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (workItemId) params.set("work_item_id", workItemId);
  const query = params.toString();
  return `${WORKFLOW_RUNS_PATH}/startable${query ? `?${query}` : ""}`;
}

export function startRunBody(
  workflowKey: string,
  workItemId: string,
  repository = "",
  branch = "",
  runtimeTarget: RuntimeTargetOption["target"] | null = null,
): Record<string, unknown> {
  // Repository (provider:path) and branch are optional; empty → the platform's default for the item.
  const body: Record<string, unknown> = { workflow_key: workflowKey, work_item_id: workItemId };
  if (repository.trim()) body.repository = repository.trim();
  if (branch.trim()) body.branch = branch.trim();
  // Where the run executes; absent: the Server.
  if (runtimeTarget) body.runtime_target = runtimeTarget;
  return body;
}

export function runsListPath(status: string): string {
  return status
    ? `${WORKFLOW_RUNS_PATH}?status=${encodeURIComponent(status)}`
    : WORKFLOW_RUNS_PATH;
}

export function workItemLimitsPath(workItemId: string): string {
  return `${WORKFLOW_RUNS_PATH}/work-items/${encodeURIComponent(workItemId)}/limits`;
}

// The Work item's loop override as the API takes it: a whole number ≥ 1, or nothing (the workflow's own n).
export function loopLimitBody(
  draft: string,
): { loop_limit?: number } | { error: string } {
  const text = draft.trim();
  if (!text) return {};
  const value = Number(text);
  return Number.isInteger(value) && value >= 1
    ? { loop_limit: value }
    : { error: "Enter a whole number of at least 1." };
}

export function runViewPath(runId: string): string {
  return `${WORKFLOW_RUNS_PATH}/${encodeURIComponent(runId)}`;
}
