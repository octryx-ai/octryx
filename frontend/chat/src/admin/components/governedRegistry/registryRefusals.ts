// Human text for the governed registries' coded refusals. The code is always shown next to the
// text; an unknown code is shown as-is rather than hidden behind a generic message.
import { RegistryApiError } from "./registryApi";

const TEXT: Record<string, string> = {
  governance_approval_required: "Publishing needs the governance approval created at submit.",
  governance_approval_refused: "The governance approval does not allow publishing (see the gate status or reason).",
  request_invalid: "The request was rejected as malformed.",
  http_401: "Your session has expired; sign in again.",
  http_403: "Authoring needs the admin or owner role in this workspace.",
  http_404: "Not found.",
};

// Approval gate statuses returned inside governance_approval_refused.
const GATE_TEXT: Record<string, string> = {
  pending: "The approval is still pending: a second admin has to approve it in Approvals.",
  rejected: "The approval was rejected.",
  missing: "The approval no longer exists.",
  mismatched: "The approval belongs to other content (digest or revision changed).",
  invalid_self_approval: "Four-eyes: the approval must be decided by a different admin than the submitter.",
  missing_approver: "The approval records no approver.",
  approver_not_authorized: "The approver is not admin or owner of this workspace.",
  approved: "Approved by a second admin.",
  approved_self_approval: "Self-approved under the approval rule.",
  approved_dev_self_approval: "Self-approved under the local development exception (audited).",
};

// Reasons a single-step publish (`self_approve`) was refused.
const SELF_APPROVAL_REASON_TEXT: Record<string, string> = {
  self_approval_not_allowed:
    "You cannot approve this change yourself: the approval rule requires a second admin, or another admin submitted this revision.",
  approval_not_pending: "The review approval is no longer pending (already decided); reload and check it.",
  review_approval_missing: "This revision has no review approval to approve; submit it first.",
};

export type Refusal = { code: string; text: string; detail?: string };

export function describeRefusal(error: unknown): Refusal {
  if (error instanceof RegistryApiError) {
    const gate = error.facts.approval_gate as { status?: string } | undefined;
    const reason = typeof error.facts.reason === "string" ? error.facts.reason : null;
    const findings = Array.isArray(error.facts.findings) ? (error.facts.findings as Array<{ code?: string }>) : null;
    const detail = gate?.status
      ? `${gate.status}: ${GATE_TEXT[gate.status] ?? "see the approval"}`
      : reason
        ? `${reason}: ${SELF_APPROVAL_REASON_TEXT[reason] ?? "see the approval rule"}`
        : findings
          ? `${findings.length} error findings: ${Array.from(new Set(findings.map((item) => item.code))).join(", ")}`
          : undefined;
    return { code: error.code, text: TEXT[error.code] ?? error.message, detail };
  }
  return { code: "client_error", text: error instanceof Error ? error.message : String(error) };
}
