// Emergency stop wording and payload readers: button label, preview, result and history.
import type { OpsRun } from "./operationsTypes";
import { list, record, text } from "./operationsValues";
import { shortFolder } from "./operationsWhere";

// ---- Emergency stop (contract §5) ------------------------------------------------------------------------------

export function isEmergencyStopped(run: Partial<Pick<OpsRun, "status" | "pauseReason">>): boolean {
  return run.status === "paused" && run.pauseReason === "emergency_stop";
}

/**
 * The stop button's label, or null when the viewer may not stop this scope: one Workspace for whoever reads it
 * through the admin route (platform admins, its admins and owners); the whole platform for platform admins only.
 */
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

/** "2 runs pause and 1 device job stops."; "Nothing runs here right now." for an empty preview. */
export function previewSentence(preview: StopPreview): string {
  if (!preview.runs.length && !preview.jobs.length) return "Nothing runs here right now; the stop only records your reason.";
  return `${plural(preview.runs.length, "run pauses", "runs pause")} and ${plural(preview.jobs.length, "device job stops", "device jobs stop")}.`;
}

/** After the stop: "Stopped: 2 runs paused, 1 device job stopped." */
export function stopResultText(payload: unknown): string {
  const body = record(payload);
  const runs = list(body?.paused_runs).length;
  const jobs = list(body?.stopped_device_jobs).length;
  return `Stopped: ${plural(runs, "run", "runs")} paused, ${plural(jobs, "device job", "device jobs")} stopped.`;
}

export type StopRecord = { id: string; at: string | null; reason: string; by: string; runs: number; jobs: number };

export function readStopHistory(payload: unknown): StopRecord[] {
  return list(record(payload)?.stops).map(record).filter((row): row is Record<string, unknown> => Boolean(row && text(row.id)))
    .map((row) => ({
      id: text(row.id), at: text(row.at) || null, reason: text(row.reason), by: nameOf(row.by) || "Someone",
      runs: list(row.paused_runs).length, jobs: list(row.stopped_device_jobs).length,
    }));
}

/** "2 runs · 1 job" for a history row. */
export function stopCountText(record: Pick<StopRecord, "runs" | "jobs">): string {
  return `${plural(record.runs, "run", "runs")} · ${plural(record.jobs, "job", "jobs")}`;
}
