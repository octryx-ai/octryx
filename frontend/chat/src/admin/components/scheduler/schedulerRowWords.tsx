// Schedulers tab: a scheduler row in words (starts, next and last run, state) and its toggle and delete wording.
import { formatRelativeTime } from "../../utils/formatters";
import { formatRelative } from "../../utils/dateTime";
import type { StatusTone } from "../../../layout/StatusLabel";
import type { WorkerStatusView } from "./workerApplicationModel";
import type { PanelScheduler } from "../taskTypes";

// "3 h ago · success" in words; "Not run yet" when the server reports no run.
export function lastRunLine(scheduler: PanelScheduler): string {
  return scheduler.last_run?.at
    ? `${formatRelativeTime(scheduler.last_run.at)} · ${scheduler.last_run.status}`
    : "Not run yet";
}

// The next run in words: the server's next_run, else the worker's registered next run; none while paused.
export function nextRunLine(scheduler: PanelScheduler, worker: WorkerStatusView): string {
  if (!scheduler.is_active) return "Paused";
  const words = scheduler.next_run ? formatRelative(scheduler.next_run, "") : "";
  return words || worker.nextRun || "—";
}

const WORKER_TONES: Record<WorkerStatusView["tone"], StatusTone> = {
  applied: "neutral",
  waiting: "info",
  paused: "neutral",
  problem: "problem",
  unknown: "neutral",
};

// One state per row. A paused scheduler reads "Paused"; an active one shows the worker status,
// whose one-sentence reason is the tooltip and is spelled out in the side panel.
export function schedulerState(scheduler: PanelScheduler, worker: WorkerStatusView): { label: string; tone: StatusTone } {
  if (!scheduler.is_active) return { label: "Paused", tone: "neutral" };
  return { label: worker.label, tone: WORKER_TONES[worker.tone] };
}

export function startsLine(scheduler: PanelScheduler): string {
  const action = scheduler.task_name || "an action";
  return scheduler.workspace_name ? `${action} · ${scheduler.workspace_name}` : action;
}

export function toggleLabel(scheduler: PanelScheduler): string {
  return scheduler.is_active ? "Pause" : "Resume";
}

export function deleteQuestion(
  scheduler: PanelScheduler,
  onDeleteScheduler: (id: string, name: string) => void | Promise<void>,
) {
  return {
    title: `Delete scheduler ${scheduler.name}?`,
    body: (
      <p>
        {scheduler.managed_by_work
          ? "Its action no longer runs on this schedule. Saving the intake in Work › Intake sets it up again."
          : "Its action no longer runs on this schedule. The action itself stays."}
      </p>
    ),
    confirmLabel: `Delete ${scheduler.name}`,
    done: `Scheduler ${scheduler.name} deleted.`,
    run: async () => { await onDeleteScheduler(scheduler.id, scheduler.name); },
  };
}
