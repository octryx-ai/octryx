import { readableModelName } from "./modelNames";
import { readRemedy } from "./remedyModel";
import type { DeviceJob, JobApproval, JobDenial, JobEvent } from "./deviceJobTypes";

const text = (value: unknown): string => (typeof value === "string" ? value : "");
const record = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};

export function readApproval(raw: unknown): JobApproval | null {
  const item = record(raw);
  if (!text(item.id)) return null;
  return {
    id: text(item.id),
    tool: text(item.tool) || "tool",
    inputPreview: text(item.input_preview),
    status: text(item.status) || "pending",
    canAllowJobEdits: item.can_allow_job_edits === true,
    expiresAt: text(item.expires_at) || null,
  };
}

function readEvent(raw: unknown): JobEvent | null {
  const item = record(raw);
  return typeof item.seq === "number" && text(item.type) ? { seq: item.seq, type: text(item.type), body: record(item.body) }
    : null;
}

export function readJob(raw: unknown, previous?: DeviceJob): DeviceJob | null {
  const item = record(raw);
  if (!text(item.id)) return null;
  const events = Array.isArray(item.events) ? item.events.map(readEvent).filter((event): event is JobEvent => !!event)
    : previous?.events ?? [];
  const approvals = Array.isArray(item.approvals)
    ? item.approvals.map(readApproval).filter((approval): approval is JobApproval => !!approval)
    : previous?.approvals ?? [];
  return {
    id: text(item.id),
    deviceId: text(item.device_id),
    deviceName: text(item.device_name) || previous?.deviceName || "your device",
    folder: text(item.folder),
    profile: text(item.profile),
    model: text(item.model) || null,
    requestedModel: text(item.requested_model),
    engine: text(item.engine) || previous?.engine || null,
    status: text(item.status),
    statusReason: text(item.status_reason) || null,
    turnId: text(item.turn_id) || null,
    stopping: item.stopping === true,
    lastEventSeq: typeof item.last_event_seq === "number" ? item.last_event_seq : previous?.lastEventSeq ?? 0,
    events,
    approvals,
    denials: previous?.denials ?? [],
  };
}

export function readJobs(raw: unknown): DeviceJob[] | null {
  const items = record(raw).items;
  if (!Array.isArray(items)) return null;
  return items.map((item) => readJob(item)).filter((job): job is DeviceJob => !!job);
}

// null means a gap: reload from the server.
export function applyJobEvent(jobs: DeviceJob[], payload: Record<string, unknown>): DeviceJob[] | null {
  if (payload.eventType === "tool_denied") return withDenial(jobs, payload);
  const incoming = readJob(payload.job);
  if (!incoming) return jobs;
  const previous = jobs.find((job) => job.id === incoming.id);
  const events = [...(previous?.events ?? [])];
  const seq = payload.seq;
  if (typeof seq === "number") {
    const last = events.length ? events[events.length - 1].seq : 0;
    if (seq > last + 1 && previous) return null;
    if (seq > last) events.push({ seq, type: text(payload.eventType), body: record(payload.body) });
  }
  let approvals = [...(previous?.approvals ?? [])];
  const approval = readApproval(payload.approval);
  if (approval) {
    approvals = approvals.some((item) => item.id === approval.id)
      ? approvals.map((item) => (item.id === approval.id ? approval : item))
      : [...approvals, approval];
  }
  const merged = { ...incoming, deviceName: incoming.deviceName, engine: incoming.engine ?? previous?.engine ?? null, events, approvals,
    denials: previous?.denials ?? [] };
  return previous ? jobs.map((job) => (job.id === merged.id ? merged : job)) : [...jobs, merged];
}

function withDenial(jobs: DeviceJob[], payload: Record<string, unknown>): DeviceJob[] {
  const id = text(payload.job_id);
  if (!jobs.some((job) => job.id === id)) return jobs;
  const denial: JobDenial = { turnId: text(payload.turn_id) || null, tool: text(payload.tool), message: text(payload.message),
    remedy: readRemedy(payload.remedy) };
  return jobs.map((job) => (job.id === id ? { ...job, denials: [...job.denials, denial] } : job));
}

// Every server runner was busy: the turn starts when one frees (backend ``runner_queue``); Stop cancels it.
export const WAITING_RUNNER = "waiting_runner";

export type JobState = { label: string; tone: "running" | "done" | "stopped" | "attention"; live: boolean };

const REASONS: Record<string, string> = {
  device_offline: "the device went offline",
  device_paused: "the device is paused",
  device_busy: "the device runs as many chats as it allows",
  folder_not_allowlisted_on_device: "the folder is not allowed on the device",
  profile_unavailable_on_device: "the profile is not available on the device",
  stopped_by_owner: "stopped by you",
  cancelled_by_owner: "cancelled by you before a server runner took it",
  pipeline_done: "the CI pipeline ran; nothing was left for the model",
  stopped: "stopped by you",
  paused: "the device was paused",
  timed_out: "the job ran longer than the Workspace allows",
  seat_mode_forbidden: "the Workspace does not allow the seat profile",
  codex_seat_mode_forbidden: "the Workspace does not allow Codex with a ChatGPT subscription",
  claude_agent_sdk_missing: "octryx-claude on the device needs an update",
  claude_not_found: "Claude Code is not installed on the device",
  claude_initialize_timeout: "Claude Code on the device did not start in time (see `octryx-claude device logs`)",
  claude_start_failed: "Claude Code on the device did not start (see `octryx-claude device logs`)",
  device_folder_not_accessible: "the background service on the device cannot read the folder",
  model_invalid: "the model id is not valid",
  model_not_offered: "the device's profile does not offer that model",
};

export const jobModelLabel = (job: DeviceJob) => {
  const model = job.model || job.requestedModel;
  return `${job.profile} · ${model ? readableModelName(model) : "device default model"}`;
};

// Only while the thread still runs there, so a thread last answered by the Server opens on the Server.
export function restoresDeviceTarget(job: DeviceJob | undefined,
  messages: { role?: string; model?: string | null; origin?: string | null }[] | null | undefined): boolean {
  if (!job) return false;
  if (job.status === WAITING_RUNNER || job.status === "offered" || job.status === "running") return true;
  const answers = (messages ?? []).filter((message) => message.role === "assistant");
  const newest = answers[answers.length - 1];
  // A device answer names the model it ran on; the server marks it with origin "device".
  return !newest || newest.origin === "device" || String(newest.model ?? "").startsWith("device:");
}

export const reasonText = (reason: string | null) => (reason ? REASONS[reason] ?? reason.replace(/_/g, " ") : "");

const INTERRUPTED = new Set(["service_restarted", "service_stopped", "turn_stalled"]);
const FOLDER_NOT_ACCESSIBLE = "device_folder_not_accessible";

export function folderAccessText(job: DeviceJob): string {
  const rejected = [...job.events].reverse().find((event) => event.type === "job_rejected"
    && text(event.body.reason) === FOLDER_NOT_ACCESSIBLE);
  const python = text(rejected?.body.service_python) || "the Python of octryx-claude";
  if (text(rejected?.body.os) && text(rejected?.body.os) !== "macos") {
    return `The background service on ${job.deviceName} cannot read ${job.folder}; check its permissions or use a folder in your home.`;
  }
  return `macOS blocks the background service from ${job.folder}; allow it under System Settings → Privacy & Security → `
    + `Full Disk Access / Files & Folders for ${python}, or use a folder in your home.`;
}

export function jobState(job: DeviceJob, finished: Record<string, unknown> | null): JobState {
  if (job.status === WAITING_RUNNER) return { label: "Waiting for a server runner", tone: "running", live: true };
  if (job.statusReason === "cancelled_by_owner") return { label: "Cancelled", tone: "stopped", live: false };
  if (job.status === "offered") return { label: "Starting on the device", tone: "running", live: true };
  if (job.status === "running") return { label: job.stopping ? "Stopping" : "Running", tone: "running", live: true };
  if (job.statusReason === FOLDER_NOT_ACCESSIBLE && (job.status === "rejected" || job.status === "idle")) {
    return { label: `Not started: ${folderAccessText(job)}`, tone: "attention", live: false };
  }
  // The run had moved on after the launcher ran the CI pipeline: a finished job, not a rejection.
  if (job.statusReason === "pipeline_done") return { label: "Done: CI pipeline ran", tone: "done", live: false };
  if (job.status === "rejected") return { label: `Not started: ${reasonText(job.statusReason)}`, tone: "attention", live: false };
  if (job.status === "device_lost") return { label: "Device lost: it did not come back in time", tone: "stopped", live: false };
  if (job.status === "failed") return { label: `Failed: ${reasonText(job.statusReason)}`, tone: "stopped", live: false };
  if (job.statusReason && INTERRUPTED.has(job.statusReason)) return { label: "Interrupted — send again", tone: "attention", live: false };
  const outcome = text(finished?.status);
  if (outcome === "stopped" || job.statusReason === "stopped_by_owner") return { label: "Stopped", tone: "stopped", live: false };
  if (outcome && outcome !== "success") {
    return { label: `Ended: ${reasonText(job.statusReason || outcome)}`, tone: "stopped", live: false };
  }
  return { label: "Done", tone: "done", live: false };
}

export function secondsLeft(expiresAt: string | null, now: number = Date.now()): number {
  if (!expiresAt) return 0;
  const at = Date.parse(expiresAt);
  return Number.isNaN(at) ? 0 : Math.max(0, Math.round((at - now) / 1000));
}

export const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
