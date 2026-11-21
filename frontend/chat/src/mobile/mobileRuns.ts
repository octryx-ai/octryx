// Workflow runs on the phone: the list (Work › Runs' rows, `view=work`), its filters, and the run view's
// steps. Pure; the state words and tones come from the web's run models, so the phone and the desktop read the same.

import type { StatusTone } from "../layout/StatusLabel";
import { runWorkflowName } from "../chat/workflowRun/runBarModel";
import { workflowRunLine, type RunLine } from "./engineSeatModel";
import { runStatusLabel } from "../chat/workflowRun/workflowRunStatus";
import { type RunNode, type WorkflowRun } from "../chat/workflowRun/workflowRunTypes";

export type RunListRow = {
  id: string;
  title: string;
  // "OCX-23 · Order history" when the run works on a Work item, else the run's own title.
  subject: string;
  workflow: string;
  status: string;
  label: string;
  tone: StatusTone;
  // "Implement · phase 2 of 2", or the step outside the phases ("Product owner: ship it or answer").
  step: string;
  projectId: string;
  workItemId: string;
  sessionId: string;
  updatedAt: string;
  needsYou: boolean;
  /** The coding engine and route; null for a run without either (a Server run). */
  line: RunLine | null;
};

export type RunFilter = "needs" | "active" | "finished" | "all";

export const RUN_FILTERS: { key: RunFilter; label: string }[] = [
  { key: "needs", label: "Needs you" },
  { key: "active", label: "Active" },
  { key: "finished", label: "Finished" },
  { key: "all", label: "All" },
];

const FINISHED = new Set(["completed", "stopped", "failed"]);
const WAITING = new Set(["waiting", "paused"]);

const text = (value: unknown) => (typeof value === "string" ? value : "");
const record = (value: unknown) => (value && typeof value === "object" ? (value as Record<string, unknown>) : null);

/** The colour of a run's state: only exceptions are coloured (it waits for a person, it failed); running is info. */
export function runTone(status: string): StatusTone {
  if (status === "failed") return "problem";
  if (WAITING.has(status)) return "attention";
  if (status === "running") return "info";
  return "neutral";
}

function stepText(step: Record<string, unknown> | null): string {
  if (!step) return "";
  const title = text(step.title);
  const index = typeof step.index === "number" ? step.index : null;
  const total = typeof step.total === "number" ? step.total : 0;
  if (title && index && total) return `${title} · phase ${index} of ${total}`;
  return title;
}

export function readRunRows(raw: unknown): RunListRow[] {
  const runs = record(raw)?.runs;
  return (Array.isArray(runs) ? runs : []).flatMap((entry) => {
    const run = record(entry);
    if (!run || !text(run.id)) return [];
    const status = text(run.status);
    const item = record(run.work_item);
    const key = text(item?.key) || text(run.ticket_key);
    const subject = key ? [key, text(item?.title)].filter(Boolean).join(" · ") : text(run.title);
    return [{
      id: text(run.id),
      title: text(run.title),
      subject: subject || "Workflow run",
      workflow: text(run.workflow_title) || runWorkflowName({ workflow_key: text(run.workflow_key) }),
      status,
      label: runStatusLabel({
        status,
        waiting_kind: text(run.waiting_kind) || null,
        pause_reason: text(run.pause_reason) || null,
        outcome: text(run.outcome) || null,
      }),
      tone: runTone(status),
      step: FINISHED.has(status) ? "" : stepText(record(run.step)),
      projectId: text(run.project_id),
      workItemId: text(run.work_item_id),
      sessionId: text(run.session_id),
      updatedAt: text(run.updated_at),
      needsYou: WAITING.has(status),
      line: workflowRunLine(run),
    }];
  });
}

export function runMatches(row: Pick<RunListRow, "status" | "needsYou">, filter: RunFilter): boolean {
  if (filter === "needs") return row.needsYou;
  if (filter === "active") return !FINISHED.has(row.status);
  if (filter === "finished") return FINISHED.has(row.status);
  return true;
}

export function runCounts(rows: RunListRow[]): Record<RunFilter, number> {
  return {
    needs: rows.filter((row) => runMatches(row, "needs")).length,
    active: rows.filter((row) => runMatches(row, "active")).length,
    finished: rows.filter((row) => runMatches(row, "finished")).length,
    all: rows.length,
  };
}

/** The tab a person lands on: what waits for them, else what is going on, else everything. */
export function defaultRunFilter(rows: RunListRow[]): RunFilter {
  const counts = runCounts(rows);
  if (counts.needs) return "needs";
  if (counts.active) return "active";
  return "all";
}

// ---- The run view's steps: the workflow's main path in its order -----------------------------------------------
// The start, the recovery boxes (pause) and the ends (outcome: done, stopped, blocked) are branches, not steps; only
// the end the run reached shows, as its last step.

export type TimelineState = "done" | "current" | "waiting" | "problem" | "next";

export type TimelineStep = { id: string; title: string; kind: string; state: TimelineState };

const KIND_LABELS: Record<string, string> = {
  phase: "Phase",
  parallel_work: "Parallel work",
  user_confirmation: "Decision",
  platform_action: "Platform step",
  review: "Review",
  outcome: "Result",
};

const OFF_PATH = new Set(["start", "pause", "outcome"]);

export const stepKindLabel = (kind: string) => KIND_LABELS[kind] ?? "Step";

export function runTimeline(run: Pick<WorkflowRun, "nodes" | "current_node" | "status">): TimelineStep[] {
  const nodes = (run.nodes ?? []).filter(
    (node: RunNode) => !OFF_PATH.has(node.kind) || node.id === run.current_node?.id,
  );
  const at = nodes.findIndex((node) => node.id === run.current_node?.id);
  // On a recovery box the path's place is unknown: no step before it is claimed done.
  const offPath = OFF_PATH.has(run.current_node?.kind ?? "") && run.current_node?.kind !== "outcome";
  return nodes.map((node, index) => {
    let state: TimelineState = "next";
    if (run.status === "completed") state = "done";
    else if (at >= 0 && index < at && !offPath) state = "done";
    else if (index === at) {
      state = run.status === "failed" ? "problem" : WAITING.has(run.status) ? "waiting" : run.status === "running" ? "current" : "done";
    }
    return { id: node.id, title: node.title || node.id, kind: node.kind, state };
  });
}

/** The run's own chat (its main session), where the agent's turns are. */
export function runMainSession(run: { sessions?: unknown }): string {
  const sessions = Array.isArray(run.sessions) ? run.sessions.map(record).filter(Boolean) : [];
  const main = sessions.find((entry) => entry?.role === "main" && entry?.active !== false) ?? sessions[0];
  return text(main?.session_id);
}

export const isFinished = (status: string) => FINISHED.has(status);
