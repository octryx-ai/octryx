// The one turn status that renders compact by default: an ordinary chat reply that finished
// without an automated verification step and needs nothing from the user. The status row (state,
// the evidence label) stays visible; only the explanatory paragraphs move behind a native disclosure.
//
// Fail closed: every condition is an exact known value. Any other state or reason, a next action, a
// decision request, a workflow proposal that is not the inert "no workflow" record, recorded
// approvals, or evidence that is not explicitly `passed` or `unsourced` keeps the full card. The
// decision reads only the server's summary, never the request or answer text.
import type { TurnExecutionSummary, TurnWorkflowProposal } from "./turnExecutionSummary.types";

// `unsourced` is explained inside the disclosure; `passed` needs no explanation. The parser maps an
// evidence value the client does not know, or a malformed one, to null (turnAnswerEvidence.ts), the
// same as "not recorded". Null therefore cannot be told apart from unknown and keeps the full card.
const COMPACT_EVIDENCE_STATES: ReadonlySet<string> = new Set(["passed", "unsourced"]);

// A `none` proposal record means "the turn ran as a plain chat without a workflow". Only reasons that
// say no workflow applies are inert here: the user chose no workflow, nothing matched, or nothing is
// published. Every other `none` reason (a proposal call that failed, timed out or was refused, a scope
// change, ...) and every other status (`needs_confirmation`, `offered`, `disabled`, unfamiliar) keeps
// the full card.
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
