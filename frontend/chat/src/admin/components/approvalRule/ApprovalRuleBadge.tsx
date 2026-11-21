import { approvalModeBadgeText, type ApprovalRule } from "./approvalRule";

// The current approval rule as a small badge (Policies status strip, skill catalog header).
export function ApprovalRuleBadge({ rule }: { rule: ApprovalRule }) {
  return (
    <span
      className={`work-badge ${rule.selfApprovalAllowed ? "work-badge--attention" : "work-badge--neutral"}`}
      title={rule.selfApprovalAllowed
        ? "An admin may approve and publish their own changes (Settings → Governance → Approval rule)."
        : "A second admin approves every governed change (Settings → Governance → Approval rule)."}
      data-testid="approval-rule-badge"
    >
      {approvalModeBadgeText(rule)}
    </span>
  );
}
