// Fail closed: anything not exactly known keeps the full card; only the server's summary is read, never request or answer text.
import type { TurnExecutionSummary, TurnWorkflowProposal } from "./turnExecutionSummary.types";

// Unknown evidence parses to null, which cannot be told from "not recorded", so null keeps the full card.
const COMPACT_EVIDENCE_STATES: ReadonlySet<string> = new Set(["passed", "unsourced"]);

// Only `none` reasons that say no workflow applies are inert; a failed, timed-out or refused proposal keeps the full card.
const INERT_NO_WORKFLOW_REASONS: ReadonlySet<string> = new Set([
  "user_selected_no_workflow",
  "no_match",
  "no_published_definitions",
]);

function isInertProposal(proposal: TurnWorkflowProposal | null): boolean {
  if (proposal === null) return true;
  return (
    proposal.status === "none" &&
    proposal.reasonCode !== null &&
    INERT_NO_WORKFLOW_REASONS.has(proposal.reasonCode) &&
    proposal.proposalId === null &&
    proposal.workflowKey === null &&
    proposal.workflowTitle === null &&
    proposal.confidence === null &&
    proposal.changeCapable === null
  );
}

export function isCompactTurnStatus(summary: TurnExecutionSummary): boolean {
  return (
    summary.state === "finished_unverified" &&
    summary.stateReason.code === "runtime_finished" &&
    summary.nextAction.kind === "none" &&
    summary.decisionRequest === null &&
    isInertProposal(summary.workflowProposal) &&
    summary.approvals.length === 0 &&
    summary.answerEvidence !== null &&
    COMPACT_EVIDENCE_STATES.has(summary.answerEvidence.state)
  );
}
