// Whether the scheduling worker has applied a scheduler, from the additive
// `worker_application` field of the scheduler list/CRUD responses.
//
// It describes registration by the worker, never a run. Anything missing, malformed or
// unknown reads "Status not available", never Applied. A next run is shown as upcoming
// only when the worker applied this exact version and the date is readable and in the future.

import type { SchedulerWorkerApplication } from "../taskTypes";

export const WORKER_APPLICATION_STATUSES = [
  "paused",
  "pending",
  "applied",
  "worker_unavailable",
  "invalid_schedule",
] as const;

export type WorkerStatusTone =
  | "applied"
  | "waiting"
  | "paused"
  | "problem"
  | "unknown";

export type WorkerStatusView = {
  tone: WorkerStatusTone;
  label: string;
  detail: string;
  /** Only for an applied scheduler with a readable, future next run. */
  nextRun: string | null;
};

/** The field when it has exactly the documented shape, else null. */
export function readWorkerApplication(
  value: unknown,
): SchedulerWorkerApplication | null {
  if (!value || typeof value !== "object") return null;
  const { status, next_run_at, timezone } = value as Record<string, unknown>;
  if (!(WORKER_APPLICATION_STATUSES as readonly unknown[]).includes(status))
    return null;
  if (next_run_at !== null && typeof next_run_at !== "string") return null;
  if (timezone !== null && typeof timezone !== "string") return null;
  return { status, next_run_at, timezone } as SchedulerWorkerApplication;
}

// "Mon 5 Oct 2026, 09:00 (Europe/Zurich)": built from parts so locale punctuation cannot drift.
function formatInZone(at: Date, timezone: string | null): string {
  const options: Intl.DateTimeFormatOptions = {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  };
  const render = (zone: string) => {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("en-GB", { ...options, timeZone: zone })
        .formatToParts(at)
        .map((part) => [part.type, part.value]),
    );
    return `${parts.weekday} ${parts.day} ${parts.month} ${parts.year}, ${parts.hour}:${parts.minute} (${zone})`;
  };
  if (timezone) {
    try {
      return render(timezone);
    } catch {
      // An unknown zone name falls through to UTC rather than to the browser's zone.
    }
  }
  return render("UTC");
}

const UNKNOWN: WorkerStatusView = {
  tone: "unknown",
  label: "Status not available",
  detail:
    "This server did not report whether the scheduling worker has applied this scheduler.",
  nextRun: null,
};

export function presentWorkerApplication(
  value: unknown,
  now: Date,
): WorkerStatusView {
  const application = readWorkerApplication(value);
  if (!application) return UNKNOWN;
  switch (application.status) {
    case "paused":
      return {
        tone: "paused",
        label: "Paused",
        detail:
          "This schedule adds no new runs to the queue while paused. Runs it already queued or that are running are not cancelled, and other triggers of the linked action are not affected.",
        nextRun: null,
      };
    case "pending":
      return {
        tone: "waiting",
        label: "Waiting for the worker",
        detail:
          "Saved, but the scheduling worker has not confirmed this version yet. Check again in a moment.",
        nextRun: null,
      };
    case "worker_unavailable":
      return {
        tone: "problem",
        label: "No scheduling worker",
        detail:
          "No scheduling worker is registering schedules right now, so this schedule adds no new runs to the queue until one is available. Runs already queued are not affected and may still start.",
        nextRun: null,
      };
    case "invalid_schedule":
      return {
        tone: "problem",
        label: "Schedule not usable",
        detail:
          "The scheduling worker could not schedule this expression. Edit the schedule to fix it.",
        nextRun: null,
      };
    case "applied": {
      if (application.next_run_at === null) {
        return {
          tone: "applied",
          label: "Applied by the worker",
          detail:
            "The worker registered this version; its schedule has no further run.",
          nextRun: null,
        };
      }
      const at = new Date(application.next_run_at);
      if (Number.isNaN(at.getTime()) || at.getTime() <= now.getTime()) {
        return {
          tone: "waiting",
          label: "Applied, next run not current",
          detail:
            "The worker's last reported next run is unreadable or already past. Check again in a moment.",
          nextRun: null,
        };
      }
      return {
        tone: "applied",
        label: "Applied by the worker",
        detail:
          "The worker registered this version. This is not a record of runs.",
        nextRun: formatInZone(at, application.timezone),
      };
    }
    default:
      return UNKNOWN;
  }
}
