import type { PanelTaskRow } from "../components/taskTypes";

const generations = new Map<string, number>();

// Only the newest request may write, so a slower earlier one never overwrites a newer answer.
export function beginRunStatusRequest(taskId: string): () => boolean {
  const generation = (generations.get(taskId) ?? 0) + 1;
  generations.set(taskId, generation);
  return () => generations.get(taskId) === generation;
}

export const SUMMARY_FIELDS = [
  "run_count",
  "running_count",
  "queued_count",
  "last_run_status",
  "last_run_at",
  "next_queue_priority",
] as const;

// Only summary fields are taken, so a change saved locally while the request was in flight is never replaced.
export function mergeTaskSummary(
  tasks: PanelTaskRow[],
  fetched: PanelTaskRow[],
  taskId: string,
): PanelTaskRow[] {
  const latest = fetched.find((task) => task.id === taskId);
  if (!latest) return tasks;
  return tasks.map((task) => {
    if (task.id !== taskId) return task;
    const next: PanelTaskRow = { ...task };
    for (const field of SUMMARY_FIELDS) {
      if (field in latest)
        (next as Record<string, unknown>)[field] = latest[field];
    }
    return next;
  });
}
