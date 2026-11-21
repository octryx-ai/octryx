// Truthful step counts of a workflow run. A run's trace lists one row per node *attempt*
// (backend `FlowNodeRun`, ordered by creation): a skipped branch gets its own `skipped` row, and an
// interrupted attempt is marked `cancelled` before its retry is recorded as a new row with
// `attempt + 1` for the same node (dag_executor). Counting rows as "steps executed" therefore
// called 3 completed + 1 skipped "4 steps executed".
//
// Here a step is one node: it is counted once, by its latest attempt (highest `attempt`, the later
// row on a tie). Statuses come from the backend's closed set (dag_executor NODE_STATUS_*); a value
// outside it is shown as unknown, never as completed. The raw rows stay unchanged in the trace.
import type { FlowNodeRunTrace } from "./flowRunTypes";

const STATUS_ORDER = ["completed", "failed", "running", "paused", "pending", "cancelled", "skipped"] as const;

const STATUS_LABEL: Record<(typeof STATUS_ORDER)[number], string> = {
  completed: "completed",
  failed: "failed",
  running: "running",
  paused: "waiting",
  pending: "not started",
  cancelled: "cancelled",
  skipped: "skipped",
};

export type StepStatusCount = { status: string; label: string; count: number };

export type FlowRunStepCounts = {
  steps: number;
  attempts: number;
  byStatus: StepStatusCount[];
  // "3 completed · 1 skipped"
  summary: string;
  // "5 attempts for 4 steps" when a step was retried, otherwise "".
  attemptsNote: string;
};

type NodeRunLike = Pick<FlowNodeRunTrace, "node_id" | "status" | "attempt">;

const isKnown = (status: string): status is (typeof STATUS_ORDER)[number] => (STATUS_ORDER as readonly string[]).includes(status);

export function flowRunStepCounts(nodeRuns: NodeRunLike[] | null | undefined): FlowRunStepCounts {
  const rows = nodeRuns ?? [];
  const latest = new Map<string, NodeRunLike>();
  for (const row of rows) {
    const current = latest.get(row.node_id);
    if (!current || Number(row.attempt || 1) >= Number(current.attempt || 1)) latest.set(row.node_id, row);
  }
  const counts = new Map<string, number>();
  for (const row of latest.values()) counts.set(row.status, (counts.get(row.status) ?? 0) + 1);
  const byStatus: StepStatusCount[] = [
    ...STATUS_ORDER.filter((status) => counts.has(status)).map((status) => ({ status, label: STATUS_LABEL[status], count: counts.get(status) as number })),
    ...[...counts.keys()].filter((status) => !isKnown(status)).sort().map((status) => ({
      status,
      label: status ? `with unknown status “${status}”` : "with no status",
      count: counts.get(status) as number,
    })),
  ];
  const steps = latest.size;
  return {
    steps,
    attempts: rows.length,
    byStatus,
    summary: steps ? byStatus.map((entry) => `${entry.count} ${entry.label}`).join(" · ") : "No steps recorded",
    attemptsNote: rows.length > steps ? `${rows.length} attempts for ${steps} step${steps === 1 ? "" : "s"}` : "",
  };
}
