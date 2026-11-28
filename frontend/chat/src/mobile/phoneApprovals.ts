// The phone offers only "Allow once" and "Deny"; "Always for this Workspace" stays in the web.

import type { AttentionItem } from "../chat/companion/companionTypes";
import { approvalDecisionErrorText } from "../chat/approvalCardActions";
import { approvalPreviewKind, approvalTexts, type ApprovalPreviewKind } from "../chat/approval/approvalDetailModel";

export type PhoneDecision = "approve" | "reject";
export type PhoneDecisionAction = { kind: PhoneDecision; label: string };

export type PhoneApproval = {
  id: string;
  action: string;
  sessionId: string | null;
  workflowRunId: string | null;
  workspaceId: string | null;
  requestedBy: string | null;
  requestedByName: string | null;
  createdAt: string | null;
  payload: Record<string, unknown> | null;
  preview: ApprovalPreviewKind;
  title: string;
  subtitle: string;
  details: string[] | null;
  // A governance publication: decided on its publishing page in the web, so the phone shows it read-only.
  governance: boolean;
  decisions: PhoneDecisionAction[];
};

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const text = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value : null);

export function phoneDecisions(offered: unknown, preview: ApprovalPreviewKind = "generic"): PhoneDecisionAction[] {
  const list = Array.isArray(offered) ? offered.map(String) : [];
  const write = preview === "plan" || preview === "connector";
  const actions: PhoneDecisionAction[] = [];
  if (list.includes("deny")) actions.push({ kind: "reject", label: write ? "Reject" : "Deny" });
  if (list.includes("once")) actions.push({ kind: "approve", label: write ? "Approve" : "Allow once" });
  return actions;
}

/** The server writes UTC times without a zone ("2026-11-15T02:36:39"); read so, they are UTC, not the phone's time. */
export function utcTime(value: string | null): string | null {
  return value && /T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(value) ? `${value}Z` : value;
}

export function readPhoneApproval(value: unknown): PhoneApproval | null {
  const raw = record(value);
  const id = text(raw?.id);
  if (!raw || !id || (text(raw.status) ?? "pending").toLowerCase() !== "pending") return null;
  const payload = record(raw.payload);
  const action = text(raw.action) ?? "";
  const preview = approvalPreviewKind(payload);
  const texts = approvalTexts(raw, payload);
  // Neither a chat nor a task run asked: a governance review (the server's attention entry has no buttons either).
  const governance = text(raw.kind) === "governance" || (!text(raw.session_id) && !text(raw.task_run_id));
  return {
    id,
    action,
    sessionId: text(raw.session_id),
    workflowRunId: text(raw.workflow_run_id),
    workspaceId: text(raw.workspace_id),
    requestedBy: text(raw.requested_by),
    requestedByName: text(raw.requested_by_name),
    createdAt: utcTime(text(raw.created_at)),
    payload,
    preview,
    title: texts.title,
    subtitle: texts.subtitle,
    details: Array.isArray(raw.details) ? raw.details.map(String).filter(Boolean) : null,
    governance,
    decisions: governance ? [] : phoneDecisions(raw.offered_decisions, preview),
  };
}

export function readDecidable(payload: unknown): PhoneApproval[] {
  const items = record(payload)?.items;
  return (Array.isArray(items) ? items : []).map(readPhoneApproval).filter((item): item is PhoneApproval => item !== null);
}

/** An approval card replaces the attention entry about the same approval and the gate of its workflow run. */
export function withoutApprovals(needs: AttentionItem[], approvals: PhoneApproval[]): AttentionItem[] {
  const ids = new Set(approvals.map((item) => item.id));
  const runs = new Set(approvals.map((item) => item.workflowRunId).filter(Boolean));
  return needs.filter((item) => !ids.has(item.id) && !(item.kind === "gate" && item.runId && runs.has(item.runId)));
}

export function approvalOfItem(key: string, approvals: PhoneApproval[]): PhoneApproval | null {
  const match = /^tool_approval:(.+)$/.exec(key);
  return match ? approvals.find((item) => item.id === match[1]) ?? null : null;
}

export type PhoneApprovalLink = { kind: "run"; runId: string } | { kind: "chat"; sessionId: string } | null;

export function phoneApprovalLink(approval: Pick<PhoneApproval, "workflowRunId" | "sessionId">): PhoneApprovalLink {
  if (approval.workflowRunId) return { kind: "run", runId: approval.workflowRunId };
  if (approval.sessionId) return { kind: "chat", sessionId: approval.sessionId };
  return null;
}

export function approvalMeta(parts: { workspace: string; requestedBy: string; ago: string }): string {
  return [parts.workspace, parts.requestedBy, parts.ago ? (parts.ago === "now" ? "just now" : `${parts.ago} ago`) : ""]
    .filter(Boolean)
    .join(" · ");
}

export const REASON_CHARS = 500;

export function decisionOutcome(decision: PhoneDecision, reason = "", preview: ApprovalPreviewKind = "generic"): string {
  const note = reason.trim();
  if (decision === "approve") {
    return preview === "plan"
      ? "Approved. The writes in this plan run without asking again."
      : "Allowed once. Octryx goes on with this request; the next one asks again.";
  }
  const word = preview === "plan" || preview === "connector" ? "Rejected" : "Denied";
  return note ? `${word}. Your reason goes with it: “${note}”` : `${word}. Octryx does not run this request.`;
}

export function decisionErrorText(decision: PhoneDecision, status: number, detail = "", code: string | null = null): string {
  if (!status) return "The decision did not reach Octryx. Check the connection and try again.";
  return approvalDecisionErrorText(decision, status, detail, code);
}

export const settledByRefusal = (status: number) => [403, 404, 409].includes(status);

export type BodyRow = { key: string; label: string; value: string; json: string | null };

/** Nested values fold as indented JSON, so nothing needs horizontal scrolling at phone width. */
export function bodyRows(fields: Array<{ key: string; label: string; value: string }>): BodyRow[] {
  return fields.map((field) => {
    const value = field.value.trim();
    if (!/^[[{]/.test(value)) return { ...field, json: null };
    try {
      const parsed: unknown = JSON.parse(value);
      return parsed && typeof parsed === "object" ? { ...field, json: JSON.stringify(parsed, null, 2) } : { ...field, json: null };
    } catch {
      return { ...field, json: null };
    }
  });
}

export function foldedSize(json: string): string {
  const parsed = JSON.parse(json) as unknown;
  const count = Array.isArray(parsed) ? parsed.length : Object.keys(parsed as object).length;
  const noun = Array.isArray(parsed) ? "item" : "field";
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}
