// Decided by the server's approval view, never by the action string or the reason text.

import type { ApprovalSummary } from "../chatDecisionTypes";

export type ApprovalCardActionKind = "reject" | "retry" | "approve" | "always";
export type ApprovalDecisionKind = "approve" | "reject" | "always";

export type ApprovalCardAction = {
  kind: ApprovalCardActionKind;
  label: string;
};

export type ApprovalCardModel = {
  actions: ApprovalCardAction[];
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
    return "Timed out";
  }
  return "Pending";
}

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

export function offeredDecisions(preview: unknown): OfferedDecision[] | null {
  const raw = preview && typeof preview === "object" ? (preview as { offered_decisions?: unknown }).offered_decisions : null;
  if (!Array.isArray(raw) || !raw.length) return null;
  return raw.map((item) => String(item)).filter((item): item is OfferedDecision => OFFERED.has(item));
}

export function alwaysOffered(approval: Pick<ApprovalSummary, "changePreview">): boolean {
  return offeredDecisions(approval.changePreview?.preview)?.includes("always") ?? false;
}

export const APPROVAL_ALREADY_RESOLVED = "approval_already_resolved";
export const ALREADY_DECIDED_TEXT = "This approval was already decided.";

// Another 409 on "always" means no standing rule is allowed; any other 409 is an expired gate.
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
