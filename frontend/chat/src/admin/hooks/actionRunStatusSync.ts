// Run-status synchronisation for one Action. Pure helpers, no requests.
//
// Every run-list request for an Action takes a generation; only the newest one may write, so a
// slower earlier request (an expand load, a previous refresh) can never overwrite a newer answer.
// The Action's summary (run count, last run, queue counts) is refreshed from the existing task
// list, but only its server-computed summary fields are taken over: a name or setting saved
// locally while the request was in flight is never replaced by an older read.

import type { PanelTaskRow } from "../components/taskTypes";

const generations = new Map<string, number>();

/** Start a run-status request for `taskId`; the returned check is true only while it is the newest. */
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

/** `tasks` with the summary fields of `taskId` taken from `fetched`; unchanged when it is not listed. */
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
