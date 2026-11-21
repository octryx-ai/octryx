import type { WorkflowDecisionChoice } from "./turnExecutionSummary.types";
import { proposalAnswerBody, type ProposalAnswerBody } from "./workflowProposalAnswer";

// Options for one send. `workflowDecisions` becomes the structured
// `workflow_decisions` field of ChatSendRequest; the backend validates it
// against its closed decision catalog and never reads the prompt text.
export type MessageSendOptions = {
  workflowDecisions?: Record<string, string>;
  // An explicit workflow for this one send (an accepted workflow offer).
  workflowKey?: string;
};

export const RUN_OFFERED_WORKFLOW = "run_offered";

// An accepted workflow offer (status "offered"): the turn already ran as a
// plain chat, so the same message is sent again with the workflow chosen
// explicitly, exactly like a composer selection. Null for any other choice.
export function buildOfferedWorkflowSend(
  choice: WorkflowDecisionChoice,
): { prompt: string; options: MessageSendOptions } | null {
  if (choice.value !== RUN_OFFERED_WORKFLOW || !choice.workflowKey || !choice.prompt) {
    return null;
  }
  return { prompt: choice.prompt, options: { workflowKey: choice.workflowKey } };
}

// A decision button sends a readable prompt for the transcript plus the
// structured decision. The prompt is display text only; the decision is the
// `workflowDecisions` payload.
export function buildWorkflowDecisionSend(choice: WorkflowDecisionChoice): {
  prompt: string;
  options: MessageSendOptions;
} {
  return {
    prompt: `Decision: ${choice.label}`,
    options: { workflowDecisions: { [choice.decisionKey]: choice.value } },
  };
}

// An answer to a workflow proposal is not a new message: it goes to
// the proposal endpoint, which decides the proposal's one governed approval
// record and re-sends the pending message exactly once (apply = Allow
// once, skip = Deny: without a workflow). A phased start (`workflowStartModel.ts`) starts the run instead
// (apply, with the card's `run_on`), and "other" swaps the pending workflow
// (`workflow_key`). Returns null for an ordinary workflow decision.
export function buildWorkflowProposalDecision(
  sessionId: string | null | undefined,
  choice: WorkflowDecisionChoice,
): { path: string; body: ProposalAnswerBody } | null {
  if (!choice.proposalId || !sessionId) {
    return null;
  }
  const body = proposalAnswerBody({
    proposalId: choice.proposalId,
    decision: choice.value,
    workflowKey: choice.workflowKey,
    runOn: choice.runOn,
    repository: choice.repository,
    model: choice.model,
    budget: choice.budget,
  });
  return body
    ? { path: `/chat/api/sessions/${encodeURIComponent(sessionId)}/workflow-proposal`, body }
    : null;
}

// The request-body fragment for a send; empty when no decision is attached.
export function workflowDecisionsBody(options?: MessageSendOptions): {
  workflow_decisions?: Record<string, string>;
} {
  const decisions = options?.workflowDecisions;
  return decisions && Object.keys(decisions).length > 0
    ? { workflow_decisions: decisions }
    : {};
}
