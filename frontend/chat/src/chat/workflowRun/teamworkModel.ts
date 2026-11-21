// Teamwork (WP-D, run view): the items a "Parallel work" box really runs, from the run's ``context.work`` (frozen
// interface: backend/app/services/workflow_runs/teamwork/__init__.py). Pure: the box shows "split at run time" until
// the coordinator's plan exists, then one row per item (role, model, status, round, what it waits for, conflicts).
import { modelDisplayName } from "../header/runDetailsFacts";
import type { StatusTone } from "../../layout/StatusLabel";

export type WorkItemStatus = "pending" | "running" | "done" | "merged" | "failed" | "blocked" | "conflict";

export type WorkItem = {
  id: string;
  title?: string;
  role?: string;
  model?: string | null;
  depends_on?: string[];
  status?: string;
  iteration?: number;
  reason?: string | null;
  conflicts?: string[] | null;
  result?: { value?: string; summary?: string } | null;
  session_id?: string | null;
  branch?: string | null;
};

export type TeamWork = {
  node_id?: string;
  plan_version?: number;
  executor?: string;
  route?: string | null;
  // The run payload sends a list in plan order (teamwork/views.py); context.work itself keeps a map by id.
  items?: WorkItem[] | Record<string, WorkItem>;
};

export type WorkItemRow = {
  id: string;
  title: string;
  role: string;
  model: string;
  status: WorkItemStatus;
  label: string;
  // The design system's tones: a normal state is neutral, work in progress info, only failures are coloured.
  tone: StatusTone;
  // "round 2" once a replan reopened it; "" in its first round.
  round: string;
  // The titles of the items it waits for ("after API: export endpoint"); "" without dependencies.
  after: string;
  // Every item it waits for, for the tooltip when "after" shortens them ("after API +3").
  afterAll: string;
  // The board's parts of "after": the first title and how many more.
  afterFirst: string;
  afterMore: number;
  dependsOn: string[];
  // Why it is failed, blocked, in conflict or waiting again; the conflicting files for a conflict.
  detail: string;
  // The item's own chat (its agent session) and branch, once it started.
  sessionId: string;
  branch: string;
};

const STATUS: Record<WorkItemStatus, { label: string; tone: StatusTone }> = {
  pending: { label: "Waiting", tone: "neutral" },
  running: { label: "Running", tone: "info" },
  done: { label: "Done, merging", tone: "info" },
  merged: { label: "Merged", tone: "neutral" },
  failed: { label: "Failed", tone: "problem" },
  blocked: { label: "Blocked", tone: "problem" },
  conflict: { label: "Merge conflict", tone: "problem" },
};

// The server's short reason tokens in words (teamwork/device_items.py, plan.py); another lowercase token is not shown.
const REASON_WORDS: Record<string, string> = {
  branching: "Preparing branch",
  device_busy: "Waiting for the device",
  reopened: "Reopened by the plan",
  invalid_output: "The output was refused",
};

// Refusal codes the platform puts inside a reason sentence (teamwork/scheduler.py count_refusal, platform/dispatch.py);
// only these known codes are replaced, so a code name such as order_history_view in a reason stays as written.
const REFUSAL_WORDS: Record<string, string> = {
  start_refused: "Start refused, retrying",
  registration_refused: "the device refused the job",
  environment_not_ready: "the working folder was not ready",
  workspace_preparation_workflow_run_not_bound: "the working folder is not bound to this run",
  workspace_dirty: "the working folder has uncommitted changes",
};

function reasonText(reason: string): string {
  const value = reason.trim();
  if (value in REASON_WORDS) return REASON_WORDS[value];
  if (value in REFUSAL_WORDS) return REFUSAL_WORDS[value];
  if (/^[a-z_]+$/.test(value)) return "";
  return value.replace(/\b[a-z]+(?:_[a-z]+)+\b/g, (code) => REFUSAL_WORDS[code] ?? code);
}

const statusOf = (value: unknown): WorkItemStatus =>
  (typeof value === "string" && value in STATUS ? value : "pending") as WorkItemStatus;

/** A device job's reason (device_busy, a refusal code or a sentence with one) in words; "" for an unknown token. */
export const jobReasonText = reasonText;

/** An item status in the board's words and tone (Operations › Live reuses them). */
export function workItemStatus(value: unknown): { label: string; tone: StatusTone } {
  return STATUS[statusOf(value)];
}

/** True once the coordinator's plan has items; before that the box says "split at run time". */
export function workPlanned(work: TeamWork | null | undefined): boolean {
  return itemsOf(work).length > 0;
}

function itemsOf(work: TeamWork | null | undefined): WorkItem[] {
  const items = work?.items;
  const list = Array.isArray(items) ? items : Object.values(items ?? {});
  return list.filter((item): item is WorkItem => Boolean(item) && typeof item.id === "string");
}

/** The items in the order they can run: dependencies first, then by id (stable, cycles fall back to id order). */
export function workItemRows(work: TeamWork | null | undefined): WorkItemRow[] {
  const items = itemsOf(work);
  const byId = new Map(items.map((item) => [item.id, item]));
  const ordered: WorkItem[] = [];
  const placed = new Set<string>();
  const visit = (item: WorkItem, path: Set<string>) => {
    if (placed.has(item.id) || path.has(item.id)) return;
    path.add(item.id);
    for (const dep of [...(item.depends_on ?? [])].sort()) {
      const before = byId.get(dep);
      if (before) visit(before, path);
    }
    placed.add(item.id);
    ordered.push(item);
  };
  for (const item of [...items].sort((a, b) => a.id.localeCompare(b.id))) visit(item, new Set());
  return ordered.map((item) => {
    const status = statusOf(item.status);
    const dependsOn = (item.depends_on ?? []).filter((dep) => byId.has(dep));
    const conflicts = (item.conflicts ?? []).filter(Boolean);
    const detail = status === "conflict" && conflicts.length
      ? `Conflicts in ${conflicts.join(", ")}`
      : status === "blocked" && item.result?.summary ? item.result.summary : reasonText(item.reason ?? "");
    const depTitles = dependsOn.map((dep) => byId.get(dep)!.title || dep);
    return {
      id: item.id,
      title: item.title || item.id,
      role: item.role || "",
      model: item.model ? modelDisplayName(item.model) : "",
      status,
      label: STATUS[status].label,
      tone: STATUS[status].tone,
      round: (item.iteration ?? 1) > 1 ? `round ${item.iteration}` : "",
      after: depTitles.length ? `after ${depTitles[0]}${depTitles.length > 1 ? ` +${depTitles.length - 1}` : ""}` : "",
      afterAll: depTitles.length ? `after ${depTitles.join(", ")}` : "",
      afterFirst: depTitles[0] ?? "",
      afterMore: Math.max(0, depTitles.length - 1),
      dependsOn,
      detail: status === "merged" || status === "running" ? "" : detail,
      sessionId: item.session_id || "",
      branch: item.branch || "",
    };
  });
}

/** One line for the box's header: "4 items · 2 running · 1 merge conflict"; "split at run time" before the plan. */
export function workSummary(work: TeamWork | null | undefined): string {
  if (!workPlanned(work)) return "split at run time";
  const rows = workItemRows(work);
  const count = (status: WorkItemStatus) => rows.filter((row) => row.status === status).length;
  const parts = [`${rows.length} ${rows.length === 1 ? "item" : "items"}`];
  const add = (status: WorkItemStatus, words: string) => {
    const n = count(status);
    if (n) parts.push(`${n} ${words}`);
  };
  add("running", "running");
  add("merged", "merged");
  add("failed", "failed");
  add("blocked", "blocked");
  add("conflict", count("conflict") === 1 ? "merge conflict" : "merge conflicts");
  if (work?.route === "replan") parts.push("back to the plan");
  return parts.join(" · ");
}
