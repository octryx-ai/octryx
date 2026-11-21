import { formatClock } from "../../admin/utils/dateTime";
import { canAbort, type Job } from "./companionJobModel";
import type { AttentionAction, AttentionItem } from "./companionTypes";

// Octryx stage 1, part C: handing a run over to another person, an admin's emergency stop, and quiet hours as the
// server keeps them. Pure functions only, so unit tests read them directly.
//
// - Request: POST /api/v1/workflow-runs/{id}/handover-requests {to_user_id, reason} (the run's requester or an admin;
//   the receiver must be a member of the run's Workspace, which the server checks).
// - The receiver answers the "handover" attention item through its own actions (accept / decline); an accept answers
//   {handover, session_id}, the receiver's new thread of the run, which the companion opens.
// - Emergency stop: POST /api/v1/workflow-runs/{id}/emergency-stop {reason}, admins only, reason required.

export type HandoverCandidate = { id: string; name: string };

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const str = (value: unknown): string => (typeof value === "string" ? value.trim() : "");
const runPath = (runId: string, tail: string) => `/api/v1/workflow-runs/${encodeURIComponent(runId)}/${tail}`;

/** Whether an action accepts a handover (its answer carries the receiver's new thread). */
export function isHandoverAccept(item: AttentionItem, action: AttentionAction): boolean {
  return item.kind === "handover" && (action.key === "accept" || action.request.path.endsWith("/handover/accept"));
}

/** The receiver's new thread from an accept's answer; null when the answer has none. */
export function acceptedSessionId(payload: unknown): string | null {
  return str(record(payload)?.session_id) || null;
}

export const HANDOVER_ACCEPTED = "You now own this run.";

/** Hand over: the requester (or an admin) of a run that has not ended. */
export const canHandOver = (job: Job, isAdmin: boolean) => (job.canControl || isAdmin) && canAbort({ ...job, canControl: true });

/** Emergency stop: admins only, for a run that has not ended. */
export const canEmergencyStop = (job: Job, isAdmin: boolean) => isAdmin && canAbort({ ...job, canControl: true });

export function handoverRequest(runId: string, toUserId: string, reason: string):
  { path: string; body: Record<string, unknown> } | { error: string } {
  if (!toUserId) return { error: "Choose who takes the run over." };
  if (!reason.trim()) return { error: "Enter a reason to continue." };
  return { path: runPath(runId, "handover-requests"), body: { to_user_id: toUserId, reason: reason.trim() } };
}

export function emergencyStopRequest(runId: string, reason: string): { path: string; body: Record<string, unknown> } {
  return { path: runPath(runId, "emergency-stop"), body: { reason: reason.trim() } };
}

export const handoverRequestedText = (name: string) => `Handover requested to ${name}.`;

/**
 * Who a run can go to: the run's Workspace members (GET /api/v1/workspaces/{id}/members, direct and through groups).
 * The run's owner is never offered; the server still checks membership.
 */
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

/** The socket message that ends the job_changed nudges of one run. */
export const unwatchMessage = (runId: string) => JSON.stringify({ unwatch: runId });

/** "Quiet until 08:00" while quiet hours hold; empty otherwise. */
export function quietUntilText(quiet: { active: boolean; until: string | null }): string {
  if (!quiet.active) return "";
  return quiet.until ? `Quiet until ${formatClock(quiet.until)}` : "Quiet hours";
}

/** A refused save in plain words: invalid times get the format, anything else the server's message. */
export function quietSaveErrorText(error: { code?: string | null; message?: string } | null | undefined): string {
  if (error?.code === "invalid_quiet_hours") return "Start and end must be times like 19:00.";
  return error?.message || "Quiet hours could not be saved.";
}

export type HandoverStatus = { state: "requested" | "accepted" | "declined"; owner: string } | null;

/**
 * The latest handover of a job from its events (newest first): requested, accepted or declined, with the run's current
 * owner. After an accept the former owner no longer hands it over and reads "they own it now".
 */
export function handoverStatus(job: { events: { kind: string }[]; owner: { name: string } | null }): HandoverStatus {
  const latest = job.events.find((event) => event.kind.startsWith("handover_"));
  const state = latest?.kind.slice("handover_".length);
  if (state !== "requested" && state !== "accepted" && state !== "declined") return null;
  return { state, owner: job.owner?.name ?? "" };
}

/** "Handed over to Anna · they own it now." after the receiver accepted. */
export const handedOverText = (name: string) => `Handed over to ${name || "them"} · they own it now.`;
