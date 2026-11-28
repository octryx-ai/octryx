import type { OpsRun } from "./operationsTypes";
import { list, num, record, text } from "./operationsValues";
import { shortFolder } from "./operationsWhere";

export function isEmergencyStopped(run: Partial<Pick<OpsRun, "status" | "pauseReason">>): boolean {
  return run.status === "paused" && run.pauseReason === "emergency_stop";
}

export function stopButtonLabel(scope: { all: boolean; workspaceName: string; isPlatformAdmin: boolean; viaAdminRoute: boolean }): string | null {
  if (scope.all) return scope.isPlatformAdmin ? "Stop everything on the platform" : null;
  if (!scope.viaAdminRoute || !scope.workspaceName) return null;
  return `Stop everything in ${scope.workspaceName}`;
}

export type StopPreviewRun = { id: string; title: string; workspace: string; status: string; node: string };
export type StopPreviewJob = { id: string; folder: string; workspace: string; status: string };
export type StopPreview = { runs: StopPreviewRun[]; jobs: StopPreviewJob[] };

const nameOf = (value: unknown) => text(record(value)?.name);

export function readStopPreview(payload: unknown): StopPreview {
  const body = record(payload);
  return {
    runs: list(body?.runs).map(record).filter((row): row is Record<string, unknown> => Boolean(row && text(row.id)))
      .map((row) => ({ id: text(row.id), title: text(row.title) || "Run", workspace: nameOf(row.workspace),
        status: text(row.status), node: text(row.current_node) })),
    jobs: list(body?.device_jobs).map(record).filter((row): row is Record<string, unknown> => Boolean(row && text(row.id)))
      .map((row) => ({ id: text(row.id), folder: shortFolder(text(row.folder)), workspace: nameOf(row.workspace),
        status: text(row.status) })),
  };
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

export function previewSentence(preview: StopPreview): string {
  if (!preview.runs.length && !preview.jobs.length) {
    return "Nothing you can see runs right now; the stop records your reason and holds new starts.";
  }
  return `Of what you can see, ${plural(preview.runs.length, "run pauses", "runs pause")} and ${plural(preview.jobs.length, "device job stops", "device jobs stop")}.`;
}

// Jobs of other people's private Workspaces come only as a count.
const stoppedJobs = (body: Record<string, unknown> | null | undefined): number =>
  list(body?.stopped_device_jobs).length + (num(body?.hidden_device_jobs_stopped) ?? 0);

export function stopResultText(payload: unknown): string {
  const body = record(payload);
  const runs = list(body?.paused_runs).length;
  const jobs = stoppedJobs(body);
  return `Stopped: ${plural(runs, "run", "runs")} paused, ${plural(jobs, "device job", "device jobs")} stopped.`;
}

export type StopRecord = { id: string; at: string | null; reason: string; by: string; runs: number; jobs: number };

export function readStopHistory(payload: unknown): StopRecord[] {
  return list(record(payload)?.stops).map(record).filter((row): row is Record<string, unknown> => Boolean(row && text(row.id)))
    .map((row) => ({
      id: text(row.id), at: text(row.at) || null, reason: text(row.reason), by: nameOf(row.by) || "Someone",
      runs: list(row.paused_runs).length + (num(row.hidden_runs_paused) ?? 0), jobs: stoppedJobs(row),
    }));
}

export function stopCountText(record: Pick<StopRecord, "runs" | "jobs">): string {
  return `${plural(record.runs, "run", "runs")} · ${plural(record.jobs, "job", "jobs")}`;
}
