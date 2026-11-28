import type { StatusTone } from "../../../layout/StatusLabel";
import { PAUSE_REASON, pausedSentence } from "../../../chat/companion/companionLabels";
import { jobReasonText, workItemStatus } from "../../../chat/workflowRun/teamworkModel";
import { isEmergencyStopped } from "./operationsEmergencyStop";
import type { OpsCounts, OpsDevice, OpsItem, OpsJob, OpsProblem, OpsRun, RunState } from "./operationsTypes";

export function durationText(seconds: number | null): string {
  if (seconds === null || seconds < 60) return "";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return `${Math.floor(seconds / 86400)} d`;
}

export function agoText(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "";
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${Math.floor(seconds)} s ago`;
  return `${durationText(seconds)} ago`;
}

export function secondsSince(iso: string | null, now: number): number | null {
  if (!iso) return null;
  const at = Date.parse(iso);
  return Number.isFinite(at) ? Math.max(0, Math.round((now - at) / 1000)) : null;
}

/** Measured against the server's `generated_at`, so a skewed browser clock does not show "in 3 min". */
export function liveAge(iso: string | null, generatedAt: string | null, elapsedSeconds: number): number | null {
  const reference = generatedAt ? Date.parse(generatedAt) : NaN;
  const age = secondsSince(iso, Number.isFinite(reference) ? reference : Date.now());
  return age === null ? null : age + Math.max(0, Math.round(elapsedSeconds));
}

export function costText(usd: number | null): string {
  if (usd === null) return "";
  if (usd > 0 && usd < 0.005) return "<$0.01";
  return `$${usd.toFixed(2)}`;
}

export function problemWords(problem: Pick<OpsProblem, "reasonCode">, idleSeconds: number | null = null): string {
  switch (problem.reasonCode) {
    case "looping": return "Looping";
    case "jobs_rejected": return "Jobs refused";
    case "silent": return joinWords("Silent", durationText(idleSeconds));
    case "job_stalled": return "Stalled job";
    case "needs_you": return joinWords("Needs you", durationText(idleSeconds));
    case "waiting": return "Waiting long";
    case "stopped": return "Stopped by emergency stop";
    case "run_cost": return "High cost";
    case "seat_exhausted": return "Seat almost used up";
    // A paused run's problem carries its pause reason as the code ("action_failed", "runtime_failed", …).
    default: return PAUSE_REASON[problem.reasonCode] ? pausedSentence(problem.reasonCode) : "Problem";
  }
}

const joinWords = (...parts: string[]) => parts.filter(Boolean).join(" ");

export type StateLabel = { label: string; tone: StatusTone; title: string };

export function runStateLabel(run: Pick<OpsRun, "state" | "idleSeconds" | "problems">
  & Partial<Pick<OpsRun, "requestedBy" | "responsible" | "status" | "pauseReason">>): StateLabel {
  const worst = run.problems.find((problem) => problem.severity === "problem") ?? run.problems[0] ?? null;
  const title = worst?.title ?? "";
  // An emergency stop is no failure; the run's Continue picks it up again.
  if (run.state === "stopped" || isEmergencyStopped(run)) return { label: "Stopped by emergency stop", tone: "attention", title };
  if (run.status === "paused" && run.pauseReason === "loop_detected") return { label: "Loop detected · paused", tone: "problem", title };
  switch (run.state) {
    case "looping":
      return { label: "Looping", tone: "problem", title };
    case "problem":
      // A paused run often has no problem entry of its own in the live view; its pause reason says why.
      if (!worst && run.status === "paused" && run.pauseReason)
        return { label: problemWords({ reasonCode: run.pauseReason }), tone: "problem", title };
      return { label: worst ? problemWords(worst, run.idleSeconds) : "Problem", tone: "problem", title };
    case "silent": {
      const silent = run.problems.find((problem) => problem.reasonCode === "silent");
      return { label: joinWords("Silent", durationText(run.idleSeconds)),
        tone: silent?.severity === "problem" ? "problem" : "attention", title: silent?.title ?? title };
    }
    case "needs_you": {
      const other = waitsFor(run);
      return { label: joinWords(other ? `Waits for ${other}` : "Needs you", durationText(run.idleSeconds)), tone: "attention", title };
    }
    default:
      return { label: "Working", tone: "info", title };
  }
}

export function itemStateLabel(item: Pick<OpsItem, "status" | "problems">): StateLabel {
  const worst = item.problems.find((problem) => problem.severity === "problem") ?? item.problems[0] ?? null;
  if (worst) return { label: problemWords(worst), tone: worst.severity === "problem" ? "problem" : "attention", title: worst.title };
  const status = workItemStatus(item.status);
  return { label: status.label, tone: status.tone, title: "" };
}

export function waitsFor(run: Partial<Pick<OpsRun, "requestedBy" | "responsible">>): string {
  const person = run.responsible ?? run.requestedBy ?? null;
  return person && !person.isMe ? person.name : "";
}

const JOB_WORDS: Record<string, string> = {
  queued: "Queued",
  starting: "Starting",
  running: "Running",
  idle: "Idle",
  waiting: "Waiting",
  rejected: "Refused",
  refused: "Refused",
  completed: "Done",
  succeeded: "Done",
  failed: "Failed",
  stopped: "Stopped",
  cancelled: "Stopped",
  lost: "Lost",
};

export function jobText(job: Pick<OpsJob, "status" | "statusReason"> | null): string {
  if (!job) return "";
  const reason = job.statusReason ? jobReasonText(job.statusReason) : "";
  const status = JOB_WORDS[job.status] ?? "";
  if (!reason) return status;
  if (!status || job.status === "waiting") return reason.replace(/^./, (char) => char.toUpperCase());
  return `${status}: ${reason}`;
}

export function itemMeta(item: Pick<OpsItem, "iteration" | "dispatches5m">): string {
  return [`Iteration ${item.iteration}`, item.dispatches5m > 1 ? `${item.dispatches5m} starts in 5 min` : ""]
    .filter(Boolean).join(" · ");
}

export function runMeta(run: Pick<OpsRun, "workspace" | "workItem" | "requestedBy">): string {
  return [run.workspace?.name ?? "", run.workItem?.key ?? "", run.requestedBy?.name ?? ""].filter(Boolean).join(" · ");
}

export type CountTile = { key: RunState | "cost" | "seat"; label: string; value: string; tone: StatusTone };

export function countTiles(counts: OpsCounts): CountTile[] {
  const tile = (key: RunState, label: string, tone: StatusTone): CountTile =>
    ({ key, label, value: String(counts[key]), tone: counts[key] ? tone : "neutral" });
  return [
    tile("working", "Working", "neutral"),
    tile("needs_you", "Needs you", "attention"),
    tile("silent", "Silent", "attention"),
    tile("looping", "Looping", "problem"),
    tile("problem", "Problem", "problem"),
    // Only while something is stopped: a deliberate stop is no failure, and an empty tile would be noise.
    ...(counts.stopped ? [tile("stopped", "Stopped", "attention")] : []),
    { key: "cost", label: "API cost, last 24 h", value: costText(counts.cost24hUsd) || "$0.00", tone: "neutral" },
    // Only when seats were used; never summed with API cost.
    ...(counts.seatApiEquivalent24hUsd ? [{ key: "seat" as const, label: "Seat: would cost via API (list price), last 24 h",
      value: costText(counts.seatApiEquivalent24hUsd) || "$0.00", tone: "neutral" as const }] : []),
  ];
}

export type DeviceLabel = { label: string; tone: StatusTone };

export function deviceState(device: Pick<OpsDevice, "online" | "paused">): DeviceLabel {
  if (!device.online) return { label: "Offline", tone: "neutral" };
  if (device.paused) return { label: "Paused", tone: "attention" };
  return { label: "Online", tone: "neutral" };
}

export function slotsText(device: Pick<OpsDevice, "jobsRunning" | "maxParallelJobs">): string {
  return device.maxParallelJobs ? `${device.jobsRunning} of ${device.maxParallelJobs}` : String(device.jobsRunning);
}

/** Attention from 90 %, the seat_exhausted threshold. */
export function seatText(pct: number | null): { label: string; tone: StatusTone } {
  if (pct === null) return { label: "", tone: "neutral" };
  return { label: `${Math.round(pct)} %`, tone: pct >= 90 ? "attention" : "neutral" };
}
