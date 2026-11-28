import type { WorkflowDecisionChoice } from "./turnExecutionSummary.types";
import { proposalAnswerBody, type ProposalAnswerBody } from "./workflowProposalAnswer";

// The backend validates workflow_decisions against its closed catalog and never reads the prompt text.
export type MessageSendOptions = {
  workflowDecisions?: Record<string, string>;
  workflowKey?: string;
};

export const RUN_OFFERED_WORKFLOW = "run_offered";

// The turn already ran as plain chat, so the same message is sent again with the workflow chosen.
export function buildOfferedWorkflowSend(
  choice: WorkflowDecisionChoice,
): { prompt: string; options: MessageSendOptions } | null {
  if (choice.value !== RUN_OFFERED_WORKFLOW || !choice.workflowKey || !choice.prompt) {
    return null;
  }
  return { prompt: choice.prompt, options: { workflowKey: choice.workflowKey } };
}

export function buildWorkflowDecisionSend(choice: WorkflowDecisionChoice): {
  prompt: string;
  options: MessageSendOptions;
} {
  return {
    prompt: `Decision: ${choice.label}`,
    options: { workflowDecisions: { [choice.decisionKey]: choice.value } },
  };
}

// A proposal answer goes to the proposal endpoint, which re-sends the pending message exactly once.
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

export function workflowDecisionsBody(options?: MessageSendOptions): {
  workflow_decisions?: Record<string, string>;
} {
  const decisions = options?.workflowDecisions;
  return decisions && Object.keys(decisions).length > 0
    ? { workflow_decisions: decisions }
    : {};
}
