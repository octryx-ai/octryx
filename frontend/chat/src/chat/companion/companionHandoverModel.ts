import { formatClock } from "../../admin/utils/dateTime";
import { canAbort, type Job } from "./companionJobModel";
import type { AttentionAction, AttentionItem } from "./companionTypes";

export type HandoverCandidate = { id: string; name: string };

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const str = (value: unknown): string => (typeof value === "string" ? value.trim() : "");
const runPath = (runId: string, tail: string) => `/api/v1/workflow-runs/${encodeURIComponent(runId)}/${tail}`;
const HANDOVERS = "/api/v1/session-handovers";

export function isHandoverAccept(item: AttentionItem, action: AttentionAction): boolean {
  return (item.kind === "handover" || item.kind === "pool") && (action.key === "accept" || action.request.path.endsWith("/accept"));
}

export function acceptedSessionId(payload: unknown): string | null {
  return str(record(payload)?.session_id) || null;
}

export const HANDOVER_ACCEPTED = "You now own this run.";

export const canHandOver = (job: Job, isAdmin: boolean) => (job.canControl || isAdmin) && canAbort({ ...job, canControl: true });

export const canEmergencyStop = (job: Job, isAdmin: boolean) => isAdmin && canAbort({ ...job, canControl: true });

/** The handover form's choice for the Workspace's session pool instead of a person. */
export const TO_POOL = "pool";

export function handoverRequest(runId: string, toUserId: string, reason: string):
  { path: string; body: Record<string, unknown> } | { error: string } {
  if (!toUserId) return { error: "Choose who takes the run over." };
  if (!reason.trim()) return { error: "Enter a reason to continue." };
  const to = toUserId === TO_POOL ? {} : { to_user_id: toUserId };
  return { path: HANDOVERS, body: { run_id: runId, ...to, reason: reason.trim() } };
}

export function emergencyStopRequest(runId: string, reason: string): { path: string; body: Record<string, unknown> } {
  return { path: runPath(runId, "emergency-stop"), body: { reason: reason.trim() } };
}

export const handoverRequestedText = (name: string) => `Handover requested to ${name}.`;
export const POOLED_TEXT = "In the session pool: whoever can run it now may take it over.";

/** The run's owner is never offered; the server still checks membership. */
export function readCandidates(payload: unknown, ownerId: string): HandoverCandidate[] {
  const members = record(payload)?.members;
  const seen = new Set<string>([ownerId]);
  return (Array.isArray(members) ? members : [])
    .map((entry): HandoverCandidate | null => {
      const member = record(entry);
      return member && str(member.id) ? { id: str(member.id), name: str(member.display_name) || str(member.id) } : null;
    })
    .filter((candidate): candidate is HandoverCandidate => candidate !== null)
    .filter((candidate) => (seen.has(candidate.id) ? false : (seen.add(candidate.id), true)))
    .sort((left, right) => left.name.localeCompare(right.name));
}

export const unwatchMessage = (runId: string) => JSON.stringify({ unwatch: runId });

export function quietUntilText(quiet: { active: boolean; until: string | null }): string {
  if (!quiet.active) return "";
  return quiet.until ? `Quiet until ${formatClock(quiet.until)}` : "Quiet hours";
}

export function quietSaveErrorText(error: { code?: string | null; message?: string } | null | undefined): string {
  if (error?.code === "invalid_quiet_hours") return "Start and end must be times like 19:00.";
  return error?.message || "Quiet hours could not be saved.";
}

export type HandoverStatus = { state: "requested" | "accepted" | "declined"; owner: string } | null;

/** After an accept the former owner no longer hands it over. */
export function handoverStatus(job: { events: { kind: string }[]; owner: { name: string } | null }): HandoverStatus {
  const latest = job.events.find((event) => event.kind.startsWith("handover_"));
  const state = latest?.kind.slice("handover_".length);
  if (state !== "requested" && state !== "accepted" && state !== "declined") return null;
  return { state, owner: job.owner?.name ?? "" };
}

export const handedOverText = (name: string) => `Handed over to ${name || "them"} · they own it now.`;
