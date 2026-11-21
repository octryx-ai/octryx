// The approval detail page (backend GET /api/v1/approvals/{id}): what was asked (the change preview, stored
// masked since), who asked and who decided, where it belongs, and, while it waits, the decisions the server
// offers. Pure, so the page and its unit tests share it.
//
// The page lives in Operations › Decisions as a hidden page: /chat?area=operations&tab=approvalDetail&approval=<id>.
// The REST calls audit, the Decisions drawer and a workflow run's history link to it.

import type { StatusTone } from "../../layout/StatusLabel";
import { connectorWriteView } from "./connectorWriteView";
import { restRequestView } from "./restRequestView";
import { WRITE_PLAN_NOTE, writePlanView } from "./writePlanView";
import { offeredDecisions, type ApprovalDecisionKind } from "../approvalCardActions";

export type ApprovalDetail = {
  id: string;
  kind: "session" | "task_run" | "governance" | string;
  status: string;
  action: string;
  sessionId: string | null;
  taskRunId: string | null;
  workflowRunId: string | null;
  workspaceId: string | null;
  requestedBy: string | null;
  requestedByName: string | null;
  approvedBy: string | null;
  approvedByName: string | null;
  decisionNote: string | null;
  createdAt: string | null;
  resolvedAt: string | null;
  payload: Record<string, unknown> | null;
  // The approval in words: "Run a command on the Octryx server", and why the person is asked.
  title: string | null;
  subtitle: string | null;
  // The preview's detail lines in words, as the server serves them (`approval/presentation`); null when not served.
  details: string[] | null;
  // The decisions the server offers (`offered_decisions`); empty offers none.
  offered: Array<"once" | "always" | "deny">;
};

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const text = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value : null);

export function parseApprovalDetail(payload: unknown): ApprovalDetail | null {
  const raw = record(payload);
  const id = text(raw?.id);
  const status = text(raw?.status);
  if (!raw || !id || !status) return null;
  const preview = record(raw.payload);
  return {
    id,
    kind: text(raw.kind) ?? "session",
    status: status.toLowerCase(),
    action: text(raw.action) ?? "",
    sessionId: text(raw.session_id),
    taskRunId: text(raw.task_run_id),
    workflowRunId: text(raw.workflow_run_id),
    workspaceId: text(raw.workspace_id),
    requestedBy: text(raw.requested_by),
    requestedByName: text(raw.requested_by_name),
    approvedBy: text(raw.approved_by),
    approvedByName: text(raw.approved_by_name),
    decisionNote: text(raw.decision_note),
    createdAt: text(raw.created_at),
    title: text(raw.title),
    subtitle: text(raw.subtitle),
    details: Array.isArray(raw.details) ? raw.details.map(String).filter(Boolean) : null,
    resolvedAt: text(raw.resolved_at),
    payload: preview,
    offered: offeredDecisions({ offered_decisions: raw.offered_decisions }) ?? [],
  };
}

// ---- view state ----------------------------------------------------------------------------------------------------

export type ApprovalDetailState =
  | { kind: "loading" }
  | { kind: "message"; text: string }
  | { kind: "ready"; detail: ApprovalDetail };

/** What the page shows for an answer of GET /api/v1/approvals/{id}: one sentence for every refusal. */
export function approvalDetailState(answer: { status: number; payload?: unknown } | null): ApprovalDetailState {
  if (!answer) return { kind: "loading" };
  if (answer.status === 404) return { kind: "message", text: "This approval does not exist or is not visible to you." };
  if (answer.status === 401 || answer.status === 403) return { kind: "message", text: "You may not see this approval." };
  if (answer.status === 0) return { kind: "message", text: "The approval could not be loaded. Check the connection and reload." };
  if (answer.status < 200 || answer.status >= 300) {
    return { kind: "message", text: `The approval could not be loaded (HTTP ${answer.status}).` };
  }
  const detail = parseApprovalDetail(answer.payload);
  return detail ? { kind: "ready", detail } : { kind: "message", text: "The approval could not be read." };
}

/** The approval id of the page's address (`approval=<id>`), or null when it is missing or not an id. */
export function approvalIdFromSearch(search: string): string | null {
  const id = new URLSearchParams(search).get("approval") ?? "";
  return /^[A-Za-z0-9_-]{1,64}$/.test(id) ? id : null;
}

export const approvalDetailHref = (approvalId: string) =>
  `/chat?area=operations&tab=approvalDetail&approval=${encodeURIComponent(approvalId)}`;

// ---- what the page shows -------------------------------------------------------------------------------------------

export type ApprovalDetailStatus = { label: string; tone: StatusTone };

export function approvalDetailStatus(status: string): ApprovalDetailStatus {
  if (status === "approved") return { label: "Approved", tone: "neutral" };
  if (status === "rejected" || status === "denied") return { label: "Denied", tone: "problem" };
  if (status === "expired") return { label: "Timed out", tone: "neutral" };
  return { label: "Waiting for a decision", tone: "attention" };
}

export type ApprovalPreviewKind = "plan" | "rest" | "connector" | "generic" | "none";

/** Which preview component shows the payload: the write plan, a REST request, a connector write, or the generic one. */
export function approvalPreviewKind(payload: Record<string, unknown> | null): ApprovalPreviewKind {
  if (!payload) return "none";
  if (writePlanView(payload)) return "plan";
  if (restRequestView(payload)) return "rest";
  const toolName = typeof payload.toolName === "string" ? payload.toolName : null;
  if (connectorWriteView(payload, toolName)) return "connector";
  return "generic";
}

export type ApprovalTexts = { title: string; subtitle: string };

/**
 * The approval's title and why it is asked, the same everywhere it shows (chat card, approval page, phone). The
 * server words every approval (`approval/presentation.approval_texts`): "Run a command on the Octryx server",
 * "Comment on a Jira issue", "Write plan with 3 writes". Only a REST write keeps its own title ("POST /tickets on
 * Desk › create_ticket"): it names the request, which the server's sentence does not.
 */
export function approvalTexts(
  served: { title?: unknown; subtitle?: unknown } | null,
  payload: Record<string, unknown> | null,
): ApprovalTexts {
  const subtitle = text(served?.subtitle) ?? "";
  const rest = restRequestView(payload);
  return { title: rest ? rest.title : text(served?.title) ?? "Approval", subtitle };
}

export type ApprovalDetailAction = { kind: ApprovalDecisionKind; label: string };

/**
 * The buttons while the approval waits: the decisions the server offers (Deny, Always for this Workspace, Allow
 * once). A write plan and a connector write say Reject and Approve, as their
 * chat cards do. A governance publication is decided on its publishing page, so it gets none here; whether this
 * viewer may decide is the server's to say (a refusal is put into words).
 */
export function approvalDetailActions(
  detail: Pick<ApprovalDetail, "status" | "kind" | "offered">,
  preview: ApprovalPreviewKind = "generic",
): ApprovalDetailAction[] {
  if (detail.status !== "pending" || detail.kind === "governance") return [];
  const { offered } = detail;
  const write = preview === "plan" || preview === "connector";
  const actions: ApprovalDetailAction[] = [];
  if (offered.includes("deny")) actions.push({ kind: "reject", label: write ? "Reject" : "Deny" });
  if (offered.includes("always") && detail.kind === "session") actions.push({ kind: "always", label: "Always for this Workspace" });
  if (offered.includes("once")) actions.push({ kind: "approve", label: write ? "Approve" : "Allow once" });
  return actions;
}

/** The line next to the buttons: what the decision covers. */
export function approvalDetailNote(actions: ApprovalDetailAction[], preview: ApprovalPreviewKind): string {
  if (preview === "plan") return WRITE_PLAN_NOTE;
  return actions.some((action) => action.kind === "always")
    ? "Allow once, or for every same request in this Workspace."
    : "Only this request. The next one asks again.";
}

/** Where a decision is sent: a chat approval through the chat's own route (it resumes the turn), else the API. */
export function approvalDecisionRequest(
  detail: Pick<ApprovalDetail, "id" | "kind">,
  decision: ApprovalDecisionKind,
): { url: string; body?: string } {
  const id = encodeURIComponent(detail.id);
  if (detail.kind === "session") return { url: `/chat/api/approvals/${id}/${decision}` };
  return { url: `/api/v1/approvals/${id}/${decision}`, body: JSON.stringify({}) };
}

export type ApprovalDetailLink = { label: string; text: string; href: string };

/** The chat it was asked in, or the workflow run (whose chat is the run's session). */
export function approvalDetailLinks(detail: Pick<ApprovalDetail, "sessionId" | "workflowRunId">): ApprovalDetailLink[] {
  if (!detail.sessionId) return [];
  const href = `/chat?session_id=${encodeURIComponent(detail.sessionId)}`;
  return detail.workflowRunId
    ? [{ label: "Workflow run", text: "Open the run ›", href }]
    : [{ label: "Chat", text: "Open the chat ›", href }];
}

/** "Anna", or the short id when the server has no name. */
export function personText(name: string | null, id: string | null): string {
  return name ?? (id ? `user ${id.slice(0, 8)}` : "unknown");
}
