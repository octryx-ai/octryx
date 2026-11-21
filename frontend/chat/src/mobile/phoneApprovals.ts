// Approvals on the phone (owner: approvals also on the go; backend). Every pending approval
// the person may decide (a chat's tool call, a workflow run's, a central REST write) comes from
// GET /api/v1/approvals/decidable with its masked preview and `offered_decisions`. The phone offers only "Allow once"
// and "Deny" from that list; "Always for this Workspace" stays in the web. Pure, so the pages and their tests share it.

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
  // The server's words ("Run a command on the Octryx server"); a REST write keeps its request
  // ("POST /tickets on Demo Tickets Desk › create_ticket"). The subtitle says why the person is asked.
  title: string;
  subtitle: string;
  // The preview's detail lines in words, as the server serves them; null when it did not.
  details: string[] | null;
  // A governance publication: decided on its publishing page in the web, so the phone shows it read-only.
  governance: boolean;
  decisions: PhoneDecisionAction[];
};

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const text = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value : null);

/**
 * The buttons the phone shows: Deny and Allow once, each only when the server offers it ("deny", "once"). "Always" is
 * never a phone decision. A write plan and a connector write say Reject and Approve, as their cards in the chat and
 * the web's approval page do.
 */
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

/** GET /api/v1/approvals/decidable → the pending approvals, newest first as the server sends them. */
export function readDecidable(payload: unknown): PhoneApproval[] {
  const items = record(payload)?.items;
  return (Array.isArray(items) ? items : []).map(readPhoneApproval).filter((item): item is PhoneApproval => item !== null);
}

/**
 * One entry per thing to decide on Home. An approval card replaces the attention entry about the same approval (a
 * chat's tool approval, keyed by the approval's id) and the gate of the workflow run it belongs to (the card links to
 * the run). Everything else in "Needs you" stays.
 */
export function withoutApprovals(needs: AttentionItem[], approvals: PhoneApproval[]): AttentionItem[] {
  const ids = new Set(approvals.map((item) => item.id));
  const runs = new Set(approvals.map((item) => item.workflowRunId).filter(Boolean));
  return needs.filter((item) => !ids.has(item.id) && !(item.kind === "gate" && item.runId && runs.has(item.runId)));
}

/** A notification for a tool approval opens /m/#item=tool_approval:<id>: the approval it names, if listed. */
export function approvalOfItem(key: string, approvals: PhoneApproval[]): PhoneApproval | null {
  const match = /^tool_approval:(.+)$/.exec(key);
  return match ? approvals.find((item) => item.id === match[1]) ?? null : null;
}

export type PhoneApprovalLink = { kind: "run"; runId: string } | { kind: "chat"; sessionId: string } | null;

/** Where it was asked, inside the phone app: the workflow run, else the chat. */
export function phoneApprovalLink(approval: Pick<PhoneApproval, "workflowRunId" | "sessionId">): PhoneApprovalLink {
  if (approval.workflowRunId) return { kind: "run", runId: approval.workflowRunId };
  if (approval.sessionId) return { kind: "chat", sessionId: approval.sessionId };
  return null;
}

/** "Demo Shop · Anna · 5 min": Workspace, who asked, how long ago. */
export function approvalMeta(parts: { workspace: string; requestedBy: string; ago: string }): string {
  return [parts.workspace, parts.requestedBy, parts.ago ? (parts.ago === "now" ? "just now" : `${parts.ago} ago`) : ""]
    .filter(Boolean)
    .join(" · ");
}

export const REASON_CHARS = 500;

/** The outcome in words once the server took the decision; a write plan is confirmed as a whole. */
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

/**
 * A refused decision in words, as the web says it (`approvalDecisionErrorText`): 409 `approval_already_resolved`
 * already decided, another 409 no longer waiting, 403 not yours to decide, 404 gone, and no answer at all (status 0)
 * as a connection problem.
 */
export function decisionErrorText(decision: PhoneDecision, status: number, detail = "", code: string | null = null): string {
  if (!status) return "The decision did not reach Octryx. Check the connection and try again.";
  return approvalDecisionErrorText(decision, status, detail, code);
}

/** After these refusals the approval is not waiting for this person any more: the list is read again. */
export const settledByRefusal = (status: number) => [403, 404, 409].includes(status);

export type BodyRow = { key: string; label: string; value: string; json: string | null };

/**
 * The body as rows at phone width: plain values as they are, a nested object or list folded as indented JSON (the
 * REST preview writes nested values as JSON text), so nothing needs horizontal scrolling.
 */
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

/** "2 fields", "3 items": what a folded value holds. */
export function foldedSize(json: string): string {
  const parsed = JSON.parse(json) as unknown;
  const count = Array.isArray(parsed) ? parsed.length : Object.keys(parsed as object).length;
  const noun = Array.isArray(parsed) ? "item" : "field";
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}
