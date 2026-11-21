// Work › Coding rules › Proposed checks (From Correction to Check).
// A correction the team made twice becomes a proposed check; a person with the approver permission approves, changes
// or rejects it. Who changed a proposal does not approve it (four-eyes, as in the prompt catalog).
import type { StatusTone } from "../../../layout/StatusLabel";

export type ProposalState = "proposed" | "approved" | "rejected";
export type Occurrence = { source: string; work_item_key?: string; at: string; excerpt: string; link?: string };
export type CheckProposal = {
  id: string;
  state: ProposalState;
  evidence: { repeats: number; runs: number; sources: Record<string, number>; occurrences?: Occurrence[] };
  draft: { kind: string; lands_in: string; stack?: string; rule: { tool?: string; rule_id?: string; config?: unknown }; summary: string };
  message: { what: string; why: string; instead: string };
  old_instances: { count: number; examples: { path: string; line?: number; excerpt?: string }[] };
  proof: { state: "proven" | "failed" | "running" | "not_run"; red_on: { commit: string; path?: string }[];
    green_on: { commit: string; files_checked: number } | null };
  severity: "warning" | "error";
  enabled: boolean;
  edits: { by: string; at: string; fields: string[] }[];
  decision: { state: string; by: string; at: string; reason: string; accept_unproven?: boolean } | null;
  updated_at: string;
};
export type ProposalList = { items: CheckProposal[]; counts: Record<ProposalState, number>; may_approve: boolean; stub?: boolean };

const SOURCE_LABELS: Record<string, string> = {
  review_fixed: "fixed in review", review_change_request: "change requested in review", pr_comment: "PR comment",
  pipeline_cause: "pipeline failure", revert: "revert", refused_call: "refused call",
};
const KIND_LABELS: Record<string, string> = {
  lint_rule: "Linter rule", pattern: "Pattern rule", architecture: "Architecture boundary",
  regression_test: "Regression test", design_change: "Design change", platform_rule: "Platform rule",
};

export const kindLabel = (kind: string) => KIND_LABELS[kind] ?? kind;
export const sourceLabel = (source: string) => SOURCE_LABELS[source] ?? source.replaceAll("_", " ");

/** "3× in 3 runs · fixed in review 2, pipeline failure 1" */
export function evidenceText(proposal: Pick<CheckProposal, "evidence">): string {
  const { repeats, runs, sources } = proposal.evidence;
  const parts = Object.entries(sources).sort((a, b) => b[1] - a[1]).map(([key, count]) => `${sourceLabel(key)} ${count}`);
  return `${repeats}× in ${runs} ${runs === 1 ? "run" : "runs"}${parts.length ? ` · ${parts.join(", ")}` : ""}`;
}

export function proofStatus(proof: CheckProposal["proof"]): { label: string; tone: StatusTone; title: string } {
  if (proof.state === "proven") {
    const red = proof.red_on.length;
    return { label: "Proven", tone: "success",
      title: `Red on ${red} past ${red === 1 ? "change" : "changes"}, green on ${proof.green_on?.files_checked ?? 0} clean files.` };
  }
  if (proof.state === "failed") return { label: "Proof failed", tone: "problem", title: "The check did not catch the past mistakes, or it flagged clean code." };
  if (proof.state === "running") return { label: "Proving", tone: "info", title: "The platform runs the check on the past mistakes and on clean code." };
  return { label: "Not proven", tone: "attention", title: "The proof has not run yet." };
}

export function stateStatus(proposal: Pick<CheckProposal, "state" | "enabled" | "severity">): { label: string; tone: StatusTone } {
  if (proposal.state === "rejected") return { label: "Rejected", tone: "neutral" };
  if (proposal.state === "approved") {
    return proposal.enabled ? { label: proposal.severity === "error" ? "Enforced" : "Approved · warning", tone: "success" }
      : { label: "Switched off", tone: "neutral" };
  }
  return { label: "Proposed", tone: "attention" };
}

/** Why the viewer cannot approve, or "" when the button is theirs. */
export function approveBlocker(proposal: CheckProposal, viewerId: string, mayApprove: boolean): string {
  if (proposal.state !== "proposed") return "";
  if (!mayApprove) return "Only a person with the approver permission approves (by default the Workspace owner).";
  if (proposal.edits.some((edit) => edit.by === viewerId)) return "You changed this proposal, so a second person approves it.";
  return "";
}

const base = (workspaceId: string) => `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/check-proposals`;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...init });
  const payload = await response.json().catch(() => null) as ({ detail?: { code?: string; message?: string } } & T) | null;
  if (!response.ok) {
    const error = new Error(payload?.detail?.message ?? "The request failed. Try again.") as Error & { code?: string; status?: number };
    error.code = payload?.detail?.code; error.status = response.status;
    throw error;
  }
  return payload as T;
}

/** null when proposed checks are not available on this platform yet (404 not_available). */
export async function loadProposals(workspaceId: string): Promise<ProposalList | null> {
  try {
    return await request<ProposalList>(base(workspaceId));
  } catch (error) {
    if ((error as { status?: number }).status === 404) return null;
    throw error;
  }
}

export const loadProposal = (workspaceId: string, id: string) =>
  request<CheckProposal>(`${base(workspaceId)}/${encodeURIComponent(id)}`);
/** Approving without proof needs a note: why the team takes the risky case (it is kept in the audit log). */
export const approveProposal = (workspaceId: string, id: string, acceptUnproven: boolean, note = "") =>
  request<CheckProposal>(`${base(workspaceId)}/${encodeURIComponent(id)}/approve`,
    { method: "POST", body: JSON.stringify({ accept_unproven: acceptUnproven, note }) });
export const rejectProposal = (workspaceId: string, id: string, reason: string) =>
  request<CheckProposal>(`${base(workspaceId)}/${encodeURIComponent(id)}/reject`, { method: "POST", body: JSON.stringify({ reason }) });
export const editProposal = (workspaceId: string, id: string, message: CheckProposal["message"], summary: string) =>
  request<CheckProposal>(`${base(workspaceId)}/${encodeURIComponent(id)}/edit`, { method: "POST", body: JSON.stringify({ message, draft: { summary } }) });
export const switchProposal = (workspaceId: string, id: string, enabled: boolean, reason: string) =>
  request<CheckProposal>(`${base(workspaceId)}/${encodeURIComponent(id)}/enabled`, { method: "POST", body: JSON.stringify({ enabled, reason }) });
