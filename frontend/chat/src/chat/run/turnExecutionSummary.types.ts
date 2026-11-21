import type { StartBudgetBody } from "./startCardChoices";
// Client contract for `turn_execution_summary.v1`
// (GET /chat/api/turn-traces/{trace_id}/execution-summary).
//
// Closed enums are modelled as literal unions. Any value outside a union is
// normalized to an `unrecognized` marker by the parser so the UI can render it
// neutrally; an unknown value must never be displayed as success.

import type { TurnWorkflowChecks } from "./turnWorkflowChecks";
import type { TurnAnswerEvidence } from "./turnAnswerEvidence";
import type { TurnContentObligation } from "./turnContentObligations";
import type { TurnReplyContract } from "./turnReplyContract";
import type { TurnRunIdentity } from "./turnRunIdentityParse";

export const TURN_EXECUTION_SUMMARY_VERSION = "turn_execution_summary.v1";

export const TURN_EXECUTION_STATES = [
  "finished_unverified",
  "denied",
  "needs_approval",
  "needs_configuration",
  "needs_clarification",
  "needs_confirmation",
  // A phased workflow's start was confirmed in the chat and its run started (backend `phased_start`).
  "started",
  "blocked_unknown",
  "waiting_approval",
  "stopped",
  "failed",
  "cancelled",
  "unknown",
] as const;

export type TurnExecutionState = (typeof TURN_EXECUTION_STATES)[number];

export const TURN_NEXT_ACTION_KINDS = [
  "none",
  "contact_administrator",
  "resolve_approval",
  "complete_configuration",
  "provide_clarification",
  "confirm_workflow_proposal",
  "retry",
] as const;

export type TurnNextActionKind = (typeof TURN_NEXT_ACTION_KINDS)[number];

export type Unrecognized = { unrecognized: true; raw: string };

export type ClosedValue<T extends string> = T | Unrecognized;

export type TurnExecutionStateReason = {
  code: string | null;
  source: string | null;
  text: string | null;
};

export type TurnNextAction = {
  kind: ClosedValue<TurnNextActionKind>;
  label: string | null;
};

export type TurnGateDecision = {
  outcome: string | null;
  status: string | null;
  decisionSource: string | null;
};

// The run capability the turn executed under (`read_only` / `change` /
// `deliver`), taken from the selected workflow, never from the request mode.
export type TurnRunCapability = {
  capabilityClass: string | null;
  source: string | null;
  enforced: boolean;
  escalated: boolean;
  agentTypeIgnored: boolean;
};

export type TurnExecutionProfile = {
  version: string | null;
  profileId: string | null;
  status: string | null;
  decisionSource: string | null;
  workflowKey: string | null;
  executionStrategy: string | null;
  runCapability: TurnRunCapability | null;
  gate: TurnGateDecision | null;
};

export type TurnCapabilityUse = {
  name: string;
  calls: number | null;
  succeeded: number | null;
  failed: number | null;
};

export type TurnApprovalSummary = {
  id: string | null;
  toolName: string | null;
  status: string | null;
  createdAt: string | null;
  resolvedAt: string | null;
};

export type TurnArtifactSummary = {
  id: string | null;
  toolName: string | null;
  sizeBytes: number | null;
  createdAt: string | null;
};

// A workflow clarification's closed decision (server catalog
// `workflow_contracts/decisions.py`). The chat renders the options as
// buttons and sends the chosen value as `workflow_decisions` with the next
// message; options are never read from the assistant's message text.
export type TurnDecisionOption = {
  value: string;
  label: string;
};

export type TurnDecisionRequest = {
  decisionKey: string;
  options: TurnDecisionOption[];
  recordedValue: string | null;
};

export type WorkflowDecisionChoice = {
  decisionKey: string;
  value: string;
  label: string;
  // Set for an answer to a workflow proposal: the answer goes to the
  // proposal endpoint, which re-sends the pending message exactly once.
  proposalId?: string;
  // Set for "run with the offered workflow": the turn's own message is sent
  // again with this workflow selected explicitly.
  workflowKey?: string;
  prompt?: string;
  // A phased start's run location (an option key of the start card's "Run on").
  runOn?: string;
  // A phased start's repository (an option id of the start card's repository choice).
  repository?: string;
  // A phased start's model for a device location; empty: the device's default.
  model?: string;
  // A phased start's run budget (e.g. {cost_usd: 15}): the server puts it on the Work item before the run.
  budget?: StartBudgetBody;
  // The card shows a refusal itself (the start card, "Other workflow…"): it is thrown back, not put in the chat's
  // error line.
  inline?: boolean;
};

// Closed proposal fields of the summary. The model-written reason is
// not part of the summary; the card reads it from the thread's session state.
export const WORKFLOW_PROPOSAL_STATUSES = [
  "needs_confirmation",
  "none",
  "disabled",
  // An unasked proposal does not hold the turn; it is offered next to the answer.
  "offered",
] as const;

export type WorkflowProposalStatus =
  (typeof WORKFLOW_PROPOSAL_STATUSES)[number];

export type TurnWorkflowProposal = {
  status: ClosedValue<WorkflowProposalStatus>;
  reasonCode: string | null;
  proposalId: string | null;
  workflowKey: string | null;
  workflowTitle: string | null;
  confidence: string | null;
  changeCapable: boolean | null;
};

export type TurnExecutionSummary = {
  version: typeof TURN_EXECUTION_SUMMARY_VERSION;
  traceId: string | null;
  sessionId: string | null;
  messageId: string | null;
  runIdentity: TurnRunIdentity;
  state: ClosedValue<TurnExecutionState>;
  stateReason: TurnExecutionStateReason;
  nextAction: TurnNextAction;
  executionProfile: TurnExecutionProfile | null;
  agentName: string | null;
  modelLabel: string | null;
  capabilitiesUsed: TurnCapabilityUse[];
  approvals: TurnApprovalSummary[];
  artifacts: TurnArtifactSummary[];
  usage: { tokensIn: number | null; tokensOut: number | null };
  decisionRequest: TurnDecisionRequest | null;
  workflowProposal: TurnWorkflowProposal | null;
  // The answer evidence guard's closed decision (`turnAnswerEvidence.ts`); else null.
  answerEvidence: TurnAnswerEvidence | null;
  // The selected workflow's check result (`turnWorkflowChecks.ts`); null without checks.
  workflowChecks: TurnWorkflowChecks | null;
  // The checked reply-format result (`turnReplyContract.ts`); null for free text or no record.
  replyContract: TurnReplyContract | null;
  // What content policies masked, routed or refused in this turn (`turnContentObligations.ts`).
  contentObligations: TurnContentObligation[];
};

export type TurnExecutionSummaryLoad =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; summary: TurnExecutionSummary }
  // The server has no summary for this trace (404) or answered with an
  // unsupported contract version. Honest "unavailable", not an error.
  | { status: "unavailable"; reason: "not_found" | "unsupported_version" }
  | { status: "error" };
