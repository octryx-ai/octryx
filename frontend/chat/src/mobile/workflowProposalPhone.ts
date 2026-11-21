// The phone's view of a chat's held workflow proposal (chat parity). The phone has no turn snapshot, so it
// reads the session's own proposal: a phased one shows the start card (`workflowStartView`), any other pending one the
// plain prompt (Allow once / Other workflow… / Deny). Pure, so the unit harness can load it.

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

/** What the chat shows for the session's proposal; null when nothing waits (an offered one, or none). */
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

/** Whether the chat keeps reading its state: an unanswered proposal, or a start whose run is not linked yet. */
export function proposalStillOpen(card: PhoneProposal | null): boolean {
  if (!card) return false;
  if (!card.decided) return true;
  return card.kind === "start" && card.decided === "apply" && card.view.outcome.kind === "none";
}
