import type { ApprovalSummary, WorkflowProposalView } from "../../chatDecisionTypes";

export const AUTOMATIC_LABEL = "Automatic";
export const WORKFLOW_PROPOSAL_APPROVAL_PREFIX = "workflow_proposal.confirm:";

export type WorkflowChipState = "automatic" | "suggested" | "selected";

export type WorkflowChip = {
  state: WorkflowChipState;
  label: string;
  detail: string | null;
};

const PENDING_REASONS: Record<string, string> = {
  explicit_phased_selection: "Chosen in the composer. It runs as a workflow run for a Work item.",
  workflow_run_required: "This workflow runs as a workflow run for a Work item.",
  user_chose_other: "Chosen by you instead of the suggestion.",
};

export function proposalReasonText(reasonCode: string | null | undefined): string | null {
  return PENDING_REASONS[reasonCode ?? ""] ?? null;
}

// The platform's own chat message after a workflow start; it is no model answer.
export const WORKFLOW_START_MODEL = "workflow-start";

export function automaticWorkflowChip({
  selectedWorkflowTitle,
  proposal,
}: {
  selectedWorkflowTitle?: string | null;
  proposal?: WorkflowProposalView | null;
}): WorkflowChip {
  if (selectedWorkflowTitle) {
    return { state: "selected", label: selectedWorkflowTitle, detail: "selected in Advanced" };
  }
  const title = proposal?.workflowTitle || proposal?.workflowKey;
  if (proposal && title && proposal.status === "needs_confirmation" && !proposal.decision) {
    if (proposal.phased) return { state: "suggested", label: `${title} · waits for Start`, detail: null };
    return { state: "suggested", label: `Suggested: ${title}`, detail: proposal.reason || null };
  }
  return { state: "automatic", label: AUTOMATIC_LABEL, detail: null };
}

export function workflowChipText(chip: WorkflowChip): string {
  return chip.detail && chip.state !== "selected"
    ? `${chip.label}: ${chip.detail}`
    : chip.label;
}

export function isWorkflowProposalApproval(
  approval: Pick<ApprovalSummary, "action">,
): boolean {
  return String(approval.action || "").startsWith(WORKFLOW_PROPOSAL_APPROVAL_PREFIX);
}

export type ProposalAnswer = { value: "apply" | "skip"; label: string };

export const OTHER_WORKFLOW_LABEL = "Other workflow…";

export const PROPOSAL_ANSWERS: readonly ProposalAnswer[] = [
  { value: "apply", label: "Allow once" },
  { value: "skip", label: "Deny" },
];
