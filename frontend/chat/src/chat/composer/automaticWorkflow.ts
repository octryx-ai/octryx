// The composer has one visible state, "Automatic". The platform proposes
// a workflow before the turn; the composer shows the suggestion with its reason
// in the one workflow pill, which is also where an explicit workflow is chosen
// (an explicit `workflow_key` still works). Pure functions only, so the unit
// harness can load them.

import type { ApprovalSummary, WorkflowProposalView } from "../../chatDecisionTypes";

export const AUTOMATIC_LABEL = "Automatic";
// Approval records of held workflow proposals (backend
// `workflow_routing/proposal_approval.py`); the proposal card is their inline prompt.
export const WORKFLOW_PROPOSAL_APPROVAL_PREFIX = "workflow_proposal.confirm:";

export type WorkflowChipState = "automatic" | "suggested" | "selected";

export type WorkflowChip = {
  state: WorkflowChipState;
  label: string;
  // The short reason (model-written, bounded server-side), or a fixed note.
  detail: string | null;
};

// Why a held proposal waits, in words (reason codes of `proposal_states.py` that have no reason sentence of their own).
const PENDING_REASONS: Record<string, string> = {
  explicit_phased_selection: "Chosen in the composer. It runs as a workflow run for a Work item.",
  workflow_run_required: "This workflow runs as a workflow run for a Work item.",
  user_chose_other: "Chosen by you instead of the suggestion.",
};

export function proposalReasonText(reasonCode: string | null | undefined): string | null {
  return PENDING_REASONS[reasonCode ?? ""] ?? null;
}

// The platform's own chat message after a workflow start (`phased_start.py`); it is no model answer.
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
    // A phased start was chosen (composer or "Other workflow…"), not suggested: it waits for its start card.
    if (proposal.phased) return { state: "suggested", label: `${title} · waits for Start`, detail: null };
    return { state: "suggested", label: `Suggested: ${title}`, detail: proposal.reason || null };
  }
  return { state: "automatic", label: AUTOMATIC_LABEL, detail: null };
}

// One-line chip text: label, then the reason when there is one.
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

// The answers of the inline proposal prompt (Claude Code permission style).
export type ProposalAnswer = { value: "apply" | "skip"; label: string };

// Every pending proposal can be answered with another workflow from the catalog instead of only "Deny".
export const OTHER_WORKFLOW_LABEL = "Other workflow…";

export const PROPOSAL_ANSWERS: readonly ProposalAnswer[] = [
  { value: "apply", label: "Allow once" },
  { value: "skip", label: "Deny" },
];
