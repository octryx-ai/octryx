import { readAttentionAction } from "./companionRead";
import { type AttentionAction, type AttentionItem, type RunState } from "./companionTypes";
import { runName, runStatePhrase, targetPhrase } from "./companionLabels";

export type JobScope = "mine" | "team";
export type JobPhaseState = "done" | "active" | "problem" | "pending";
export type JobTarget = { kind: string; label: string; profile: string; reason: string; deviceName: string; online: boolean | null; folder: string | null };
export type JobEvent = { text: string; kind: string; at: string | null; technical: boolean };
export type JobPhase = { id: string; title: string; state: JobPhaseState };
export type Job = {
  runId: string;
  title: string;
  workflowKey: string;
  workItem: { id: string; key: string; title: string } | null;
  workspace: { id: string; name: string } | null;
  owner: { id: string; name: string } | null;
  state: RunState;
  status: string;
  waitingKind: string;
  pauseReason: string;
  ticketKey: string;
  currentNode: { id: string; title: string; kind: string } | null;
  phaseIndex: number | null;
  phaseCount: number;
  since: string | null;
  target: JobTarget | null;
  canControl: boolean;
};
export type JobProblem = { reason: string; code: string; message: string };
export type JobDetail = Job & {
  phases: JobPhase[]; currentStep: JobEvent | null; events: JobEvent[];
  problem: JobProblem | null; actions: AttentionAction[];
};

export const JOBS_PATH = "/api/v1/attention/jobs";
export const JOB_STATE_LABEL: Record<RunState, string> = { working: "Working", needs_you: "Needs you", done: "Finished", problem: "Problem" };
export const PHASE_STATE_LABEL: Record<JobPhaseState, string> = { done: "Done", active: "Now", problem: "Problem", pending: "Not yet" };

const RUN_STATES: RunState[] = ["working", "needs_you", "done", "problem"];
const PHASE_STATES: JobPhaseState[] = ["done", "active", "problem", "pending"];
const ACTIVE_STATUSES = ["running", "waiting", "paused"];

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const optStr = (value: unknown): string | null => (typeof value === "string" && value ? value : null);
const count = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : null);

function readNamed(value: unknown): { id: string; name: string } | null {
  const ref = record(value);
  return ref && str(ref.id) ? { id: str(ref.id), name: str(ref.name) } : null;
}

function readTarget(value: unknown): JobTarget | null {
  const target = record(value);
  if (!target) return null;
  return {
    kind: str(target.kind), label: str(target.label), profile: str(target.profile), reason: str(target.reason),
    deviceName: str(target.device_name), online: typeof target.online === "boolean" ? target.online : null,
    // Only the run's owner gets the folder; a watcher's payload has no such key.
    folder: optStr(target.folder),
  };
}

function readEvent(value: unknown): JobEvent | null {
  const event = record(value);
  if (!event || !str(event.text)) return null;
  return { text: str(event.text), kind: str(event.kind), at: optStr(event.at), technical: event.technical === true };
}

export function readJob(value: unknown): Job | null {
  const job = record(value);
  if (!job || !str(job.run_id)) return null;
  const workItem = record(job.work_item);
  const node = record(job.current_node);
  return {
    runId: str(job.run_id), title: str(job.title), workflowKey: str(job.workflow_key),
    workItem: workItem && str(workItem.id) ? { id: str(workItem.id), key: str(workItem.key), title: str(workItem.title) } : null,
    workspace: readNamed(job.workspace), owner: readNamed(job.owner),
    state: RUN_STATES.includes(job.state as RunState) ? (job.state as RunState) : "working", status: str(job.status),
    waitingKind: str(job.waiting_kind), pauseReason: str(job.pause_reason), ticketKey: str(job.ticket_key),
    currentNode: node && str(node.id) ? { id: str(node.id), title: str(node.title) || str(node.id), kind: str(node.kind) } : null,
    phaseIndex: count(job.phase_index) || null, phaseCount: count(job.phase_count) ?? 0, since: optStr(job.since),
    target: readTarget(job.runtime_target), canControl: job.can_control === true,
  };
}

export function readJobs(payload: unknown): Job[] | null {
  const jobs = record(payload)?.jobs;
  if (!Array.isArray(jobs)) return null;
  return jobs.map(readJob).filter((job): job is Job => job !== null);
}

export function readJobDetail(payload: unknown): JobDetail | null {
  const job = readJob(payload);
  if (!job) return null;
  const value = record(payload) ?? {};
  const phases = (Array.isArray(value.phases) ? value.phases : []).map((entry): JobPhase | null => {
    const phase = record(entry);
    if (!phase || !str(phase.id)) return null;
    const state = PHASE_STATES.includes(phase.state as JobPhaseState) ? (phase.state as JobPhaseState) : "pending";
    return { id: str(phase.id), title: str(phase.title) || str(phase.id), state };
  }).filter((phase): phase is JobPhase => phase !== null);
  const events = (Array.isArray(value.events) ? value.events : []).map(readEvent).filter((event): event is JobEvent => event !== null);
  const problemValue = record(value.problem);
  const problem = problemValue && (str(problemValue.message) || str(problemValue.reason))
    ? { reason: str(problemValue.reason), code: str(problemValue.code), message: str(problemValue.message) } : null;
  const actions = job.canControl && Array.isArray(value.actions)
    ? value.actions.map(readAttentionAction).filter((action): action is AttentionAction => action !== null) : [];
  return { ...job, phases, currentStep: readEvent(value.current_step), events, problem, actions };
}

const STOPPED_STATUSES = ["stopped", "aborted", "cancelled", "canceled", "emergency_stopped"];

export function isStopped(job: Pick<Job, "status">): boolean {
  return STOPPED_STATUSES.includes(job.status.toLowerCase());
}

export function jobStateLabel(
  job: Pick<Job, "state" | "status"> & Partial<Pick<Job, "currentNode" | "waitingKind" | "pauseReason">>,
): string {
  if (isStopped(job)) return "Stopped";
  return runStatePhrase(job.status, job.currentNode?.id ?? "", job.waitingKind ?? "", JOB_STATE_LABEL[job.state], job.pauseReason ?? "");
}

export function showsProblem(job: JobDetail): boolean {
  if (isStopped(job)) return false;
  return job.state === "problem" || job.problem !== null;
}

export function jobProblemItem(job: JobDetail): AttentionItem | null {
  // Only a run in problem gets the card: a working run's actions are no problem.
  if (!showsProblem(job) || (!job.problem && !job.actions.length)) return null;
  const sentence = job.problem?.message || job.problem?.reason || "The run stopped and needs a decision by its owner.";
  const reason = job.problem?.reason && job.problem.reason !== sentence ? job.problem.reason : "";
  return {
    key: `job-problem:${job.runId}`, kind: "problem", id: job.runId, title: sentence, subtitle: "", createdAt: null,
    expiresAt: null, severity: "warning", workspace: null, workItem: null, sessionId: null, runId: job.runId,
    text: reason, link: null,
    actions: job.actions, percent: null,
  };
}

export function jobsPath(scope: JobScope, workspaceId: string): string {
  const params = new URLSearchParams({ scope });
  if (scope === "team" && workspaceId) params.set("workspace_id", workspaceId);
  return `${JOBS_PATH}?${params.toString()}`;
}

export const jobPath = (runId: string) => `${JOBS_PATH}/${encodeURIComponent(runId)}`;

export function jobTitle(job: Job): string {
  return runName(job.workItem?.key || job.ticketKey || "", job.workItem?.title || job.title || "",
    job.title || job.workflowKey || "Workflow run");
}

export function phaseText(job: Job): string {
  if (!job.phaseCount) return "";
  if (job.phaseIndex) return `Phase ${job.phaseIndex} of ${job.phaseCount}`;
  if (job.state === "done") return `Phase ${job.phaseCount} of ${job.phaseCount}`;
  return job.phaseCount === 1 ? "1 phase" : `${job.phaseCount} phases`;
}

export function targetText(target: JobTarget | null): string {
  return targetPhrase(target);
}

export function jobLink(job: Job): { href: string; label: string } | null {
  return job.workItem ? { href: `/chat?area=work&work_item_id=${encodeURIComponent(job.workItem.id)}`, label: "Open work item" } : null;
}

export const canAbort = (job: Job) => job.canControl && ACTIVE_STATUSES.includes(job.status);

export function abortRequest(runId: string, reason: string): { path: string; body: Record<string, unknown> } {
  return { path: `/api/v1/workflow-runs/${encodeURIComponent(runId)}/actions`, body: { action: "abort", reason } };
}

export const watchMessage = (runId: string) => JSON.stringify({ watch: runId });

export function jobErrorText(status: number | undefined): string {
  return status === 404 ? "This job is no longer visible to you." : "This job could not be loaded.";
}

export const JOBS_EMPTY: Record<JobScope, string> = {
  mine: "None of your runs worked in the last 24 hours.",
  team: "No run of this Workspace worked in the last 24 hours.",
};
