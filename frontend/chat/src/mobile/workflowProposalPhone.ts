// The phone has no turn snapshot, so it reads the session's own proposal.

import type { WorkflowProposalView } from "../chatDecisionTypes";
import { PROPOSAL_ANSWERS, proposalReasonText, type ProposalAnswer } from "../chat/composer/automaticWorkflow";
import { workflowStartView, type WorkflowStartView } from "../chat/run/workflowStartModel";

export type PhoneProposal =
  | { kind: "start"; proposalId: string; workflowKey: string; reason: string | null; decided: "apply" | "skip" | null; view: WorkflowStartView }
  | {
      kind: "plain";
      proposalId: string;
      workflowKey: string;
      title: string;
      reason: string | null;
      decided: "apply" | "skip" | null;
      answers: readonly ProposalAnswer[];
    };

export function phoneProposal(proposal: WorkflowProposalView | null | undefined): PhoneProposal | null {
  if (!proposal || proposal.status !== "needs_confirmation" || !proposal.proposalId || !proposal.workflowKey) return null;
  const reason = proposalReasonText(proposal.reasonCode) ?? (proposal.reason?.trim() || null);
  const decided = proposal.decision ?? null;
  const base = { proposalId: proposal.proposalId, workflowKey: proposal.workflowKey, reason, decided };
  const view = workflowStartView(proposal);
  if (view) return { kind: "start", ...base, view };
  if (proposal.phased) return null; // a phased start whose card is not ready yet: the next poll brings it
  return {
    kind: "plain",
    ...base,
    title: proposal.workflowTitle || proposal.workflowKey,
    answers: PROPOSAL_ANSWERS,
  };
}

export function proposalStillOpen(card: PhoneProposal | null): boolean {
  if (!card) return false;
  if (!card.decided) return true;
  return card.kind === "start" && card.decided === "apply" && card.view.outcome.kind === "none";
}
