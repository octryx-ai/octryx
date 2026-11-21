// Which actions an inline approval card offers, decided by the server's
// explicit approval view, never by the action string or the reason text.
//
// Every approval is a tool approval with the inline permission answers:
// "Deny", "Allow once" and, when the server offers it and the viewer is a
// Workspace admin or owner, "Always for this Workspace". The hidden button is
// refused by the server too.
//
// Which decisions are offered is the server's list (the change preview's
// `offered_decisions`, ["once","deny"] plus "always" only where a standing rule
// may answer the request; never for a write to another system: REST, connector,
// MCP, database, http_request); an approval without a preview offers no "always".

import type { ApprovalSummary } from "../chatDecisionTypes";

export type ApprovalCardActionKind = "reject" | "retry" | "approve" | "always";
// The decisions an approval card sends: one record, three answers.
export type ApprovalDecisionKind = "approve" | "reject" | "always";

export type ApprovalCardAction = {
  kind: ApprovalCardActionKind;
  label: string;
};

export type ApprovalCardModel = {
  actions: ApprovalCardAction[];
  // Shown when no action remains (a decided approval without a retry).
  statusLabel: string | null;
};

export function formatApprovalStatus(value: string | null | undefined) {
  const normalized = String(value || "pending")
    .trim()
    .toLowerCase();
  if (normalized === "approved") {
    return "Approved";
  }
  if (normalized === "rejected") {
    return "Denied";
  }
  if (normalized === "expired") {
    // A gate whose timeout decided it (nobody did).
    return "Timed out";
  }
  return "Pending";
}

// "Always for this Workspace · git status": the scope the grant covers.
export function standingRuleScopeLabel(
  rule: ApprovalSummary["standingRule"],
): string | null {
  if (!rule || typeof rule.toolName !== "string" || !rule.toolName) {
    return null;
  }
  return rule.argumentClass ? `${rule.toolName} · ${rule.argumentClass}` : rule.toolName;
}

export type OfferedDecision = "once" | "always" | "deny";
const OFFERED: ReadonlySet<string> = new Set(["once", "always", "deny"]);

/** The decisions the server offers for this request (the stored preview's `offered_decisions`, written with every
 * preview by `change_preview.service.upsert_change_preview`), or null without a preview. */
export function offeredDecisions(preview: unknown): OfferedDecision[] | null {
  const raw = preview && typeof preview === "object" ? (preview as { offered_decisions?: unknown }).offered_decisions : null;
  if (!Array.isArray(raw) || !raw.length) return null;
  return raw.map((item) => String(item)).filter((item): item is OfferedDecision => OFFERED.has(item));
}

/** Whether "Always for this Workspace" is offered: only when the server's list names it. */
export function alwaysOffered(approval: Pick<ApprovalSummary, "changePreview">): boolean {
  return offeredDecisions(approval.changePreview?.preview)?.includes("always") ?? false;
}

/** The server's refusal code for a decision that came too late (409 on every decision path). */
export const APPROVAL_ALREADY_RESOLVED = "approval_already_resolved";
export const ALREADY_DECIDED_TEXT = "This approval was already decided.";

/**
 * A refused decision in words, the one place the web and the phone share. `status` is the HTTP status when known,
 * `code` the server's refusal code. An already decided approval is a 409 with `approval_already_resolved`; another 409
 * on "always" is the server saying the request may not get a standing rule (a write to another system); any other
 * 409 is a gate whose time ran out.
 */
export function approvalDecisionErrorText(
  decision: ApprovalDecisionKind,
  status: number | null,
  message = "",
  code: string | null = null,
): string {
  if (code === APPROVAL_ALREADY_RESOLVED) return ALREADY_DECIDED_TEXT;
  if (status === 409 && decision === "always") {
    return "This request cannot be allowed for the whole Workspace. Allow it once or deny it.";
  }
  if (status === 409) return "This approval is no longer waiting: its time ran out.";
  if (status === 403) return "You may not decide this approval.";
  if (status === 404) return "This approval no longer exists or is not visible to you.";
  return message ? `The decision did not go through: ${message}` : "The decision did not go through.";
}

export function approvalCardModel(
  approval: Pick<ApprovalSummary, "status" | "standingRule" | "changePreview">,
  {
    canRetry,
    canGrantStandingConfirmation = false,
  }: { canRetry: boolean; canGrantStandingConfirmation?: boolean },
): ApprovalCardModel {
  const pending =
    String(approval.status || "pending")
      .trim()
      .toLowerCase() === "pending";
  const retry: ApprovalCardAction[] = canRetry
    ? [{ kind: "retry", label: "Retry from here" }]
    : [];
  const always: ApprovalCardAction[] =
    canGrantStandingConfirmation && alwaysOffered(approval)
      ? [{ kind: "always", label: "Always for this Workspace" }]
      : [];
  const actions: ApprovalCardAction[] = pending
    ? [
        { kind: "reject", label: "Deny" },
        ...retry,
        ...always,
        { kind: "approve", label: "Allow once" },
      ]
    : retry;
  return {
    actions,
    statusLabel: actions.length ? null : formatApprovalStatus(approval.status),
  };
}
