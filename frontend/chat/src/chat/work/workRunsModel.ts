// Work › Runs (the agreed mock "Work: runs and pull requests"): what waits for a person on
// top, then every run with its step, result and cost. Data: GET /api/v1/workflow-runs?view=work[&project_id=…], the
// list rows plus `step`, `pause`, `pull_request` and `cost` per run. `cost` is the API cost; `seat_api_equivalent` and
// `seat_unpriced_calls` beside it are what the run's seat calls would cost via the API at list price,
// summed and shown apart, never added to the cost.

import { readSeat, sumSeat, type SeatFigures } from "../cost/seatEquivalent";
import { pauseTitle, runStatusLabel } from "../workflowRun/workflowRunStatus";
import { WORKFLOW_RUNS_PATH } from "../workflowRun/workflowRunRequests";
import { type RunRow } from "../workflowRun/workflowRunTypes";
import type { StatusTone } from "../../layout/StatusLabel";

export type WorkRunStep = { title: string | null; kind: string | null; index: number | null; total: number };
export type WorkRunRow = RunRow & {
  project_id?: string | null;
  created_at?: string | null;
  step?: WorkRunStep;
  pause?: { reason?: string | null; detail?: string; code?: string | null; loop_kind?: string | null } | null;
  pull_request?: { id?: number | string | null; url?: string | null; state?: string | null } | null;
  cost?: number;
  seat_api_equivalent?: number;
  seat_unpriced_calls?: number;
  /** The workflow's own title (its definition's name); optional. */
  workflow_title?: string | null;
  work_item?: { key?: string | null; title?: string | null } | null;
};

/** " · Retry for Jira sync": the work item first; the run's own title only without one. */
export function runName(run: WorkRunRow): string {
  const item = run.work_item;
  if (item?.key || item?.title) return [item.key, item.title].filter(Boolean).join(" · ");
  if (run.ticket_key && !run.title.startsWith(run.ticket_key)) return `${run.ticket_key} · ${run.title}`;
  return run.title;
}

function isStopped(run: WorkRunRow): boolean {
  return ["stopped", "aborted", "cancelled"].includes(run.status) || run.outcome === "stopped";
}

/** A run opened a pull request: it has an id or a link (Bitbucket Server answers without a link). */
export function hasPullRequest(pr: WorkRunRow["pull_request"]): boolean {
  return Boolean(pr && (pr.url || (pr.id !== null && pr.id !== undefined && pr.id !== "")));
}

export function workRunsPath(projectId?: string | null): string {
  const query = new URLSearchParams({ view: "work" });
  if (projectId) query.set("project_id", projectId);
  return `${WORKFLOW_RUNS_PATH}?${query.toString()}`;
}

const ENDED = new Set(["completed", "failed", "stopped", "cancelled", "aborted"]);

export function needsPerson(run: Pick<RunRow, "status">): boolean {
  return run.status === "waiting" || run.status === "paused";
}

/** Runs waiting for a person first (oldest wait first is not known; newest update first), then all others. */
export function splitRuns(runs: WorkRunRow[]): { waiting: WorkRunRow[]; others: WorkRunRow[] } {
  return { waiting: runs.filter(needsPerson), others: runs.filter((run) => !needsPerson(run)) };
}

/** The workflow's own title; only without one "bug-fix-reproduction" → "Bug fix reproduction" (outsider walkthrough
 * "Pr review bot"). */
export function runWorkflowTitle(run: Pick<WorkRunRow, "workflow_key" | "workflow_title">): string {
  return run.workflow_title?.trim() || workflowName(run.workflow_key);
}

/** "bug-fix-reproduction" → "Bug fix reproduction". */
export function workflowName(key: string): string {
  const words = String(key || "").replace(/[-_.]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Workflow";
}

/** The run's place next to its status: "Build · 2 of 4" on a phase, the decision's title on a decision; after the end
 * only where it stopped ("at Implement"), since the status already says how it ended. */
export function stepText(run: WorkRunRow): string {
  const step = run.step;
  if (isStopped(run) || run.status === "failed") return step?.kind === "phase" && step.title ? `at ${step.title}` : "";
  if (run.status === "completed") return "";
  if (!step?.title) return run.current_node_id ?? "–";
  if (step.index && step.total) return `${step.title} · ${step.index} of ${step.total}`;
  return step.title;
}

/** What the run produced: the pull request, the outcome, or the stop reason; "–" while nothing exists yet. */
export function resultText(run: WorkRunRow): string {
  const pr = run.pull_request;
  if (hasPullRequest(pr)) return pr?.id ? `PR #${pr.id}` : "Pull request";
  if ((ENDED.has(run.status) || isStopped(run)) && run.stop_reason) return shortText(run.stop_reason, 70);
  return "–";
}

export function shortText(text: string, limit: number): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit - 1).trimEnd()}…` : clean;
}

export function costText(cost: number | undefined): string {
  return typeof cost === "number" && cost > 0 ? `$${cost.toFixed(2)}` : "–";
}

/** The sentence under a waiting run: what the person decides, or why the run paused. */
export function waitingText(run: WorkRunRow): string {
  if (run.status === "paused") return `Paused: ${pauseTitle(run.pause_reason ?? "", run.pause ?? undefined)}`;
  const step = run.step?.title;
  const label = runStatusLabel(run);
  return step && run.step?.kind !== "phase" ? `${step} · ${label}` : label;
}

export function runTone(run: WorkRunRow): StatusTone {
  if (run.status === "failed") return "problem";
  if (run.status === "running") return "info";
  if (needsPerson(run)) return "attention";
  return "neutral";
}

export function statusWord(run: WorkRunRow): string {
  if (run.status === "waiting") return "Needs you";
  if (run.status === "paused") return "Paused";
  if (run.status === "running") return "Running";
  if (isStopped(run)) return "Stopped";
  if (run.status === "completed") return hasPullRequest(run.pull_request) ? "Shipped" : "Done";
  if (run.status === "failed") return "Failed";
  return workflowName(run.status);
}

/** The sum of the shown runs' API cost (the seat's API equivalent is summed apart, `totalSeat`). */
export function totalCost(runs: WorkRunRow[]): number {
  return runs.reduce((sum, run) => sum + (typeof run.cost === "number" ? run.cost : 0), 0);
}

/** One run's seat figures: what its seat calls would cost via the API, and its calls without a list price. */
export function runSeat(run: Pick<WorkRunRow, "seat_api_equivalent" | "seat_unpriced_calls">): SeatFigures {
  return readSeat(run, "seat_api_equivalent", "seat_unpriced_calls");
}

/** The shown runs' seat figures, summed apart from `totalCost`. */
export function totalSeat(runs: WorkRunRow[]): SeatFigures {
  return sumSeat(runs.map(runSeat));
}

/** "Waiting for you · 2" or nothing. */
export function waitingHeading(count: number): string {
  return count ? `Waiting for you · ${count}` : "";
}
