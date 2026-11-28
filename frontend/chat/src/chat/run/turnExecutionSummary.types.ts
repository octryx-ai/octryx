import type { StartBudgetBody } from "./startCardChoices";
// Values outside a union become an `unrecognized` marker: an unknown value must never be displayed as success.

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

// Taken from the selected workflow, never from the request mode.
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

// Options are never read from the assistant's message text.
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
  proposalId?: string;
  workflowKey?: string;
  prompt?: string;
  runOn?: string;
  repository?: string;
  model?: string;
  budget?: StartBudgetBody;
  // The card shows such a refusal itself, so it is thrown back, not put in the chat's error line.
  inline?: boolean;
};

export const WORKFLOW_PROPOSAL_STATUSES = [
  "needs_confirmation",
  "none",
  "disabled",
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
  answerEvidence: TurnAnswerEvidence | null;
  workflowChecks: TurnWorkflowChecks | null;
  replyContract: TurnReplyContract | null;
  contentObligations: TurnContentObligation[];
};

export type TurnExecutionSummaryLoad =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; summary: TurnExecutionSummary }
  | { status: "unavailable"; reason: "not_found" | "unsupported_version" }
  | { status: "error" };
