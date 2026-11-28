// No mode field: the workflow's capability class and the platform decide.

import { workflowDecisionsBody, type MessageSendOptions } from "./run/workflowDecisionSend";
import { executionTargetSendFields, type ExecutionTarget } from "./devices/executionTarget";

export type ChatSendSelection = {
  sessionId: string;
  projectId: string;
  runtimeTargetId: string;
  thinkingLevel: string;
  routingOverridesEnabled: boolean;
  agentId: string;
  workflowKey: string;
  executionTarget?: ExecutionTarget;
};

export function buildChatSendBody(
  prompt: string,
  selection: ChatSendSelection,
  options?: MessageSendOptions,
  // One key per draft message: a repeated send answers its thread instead of opening another.
  idempotencyKey?: string,
) {
  return {
    prompt,
    session_id: selection.sessionId,
    project_id: selection.projectId,
    runtime_target_id: selection.runtimeTargetId,
    workflow_key: options?.workflowKey || selection.workflowKey,
    thinking_level: selection.thinkingLevel,
    agent_id: selection.routingOverridesEnabled ? selection.agentId : "",
    ...workflowDecisionsBody(options),
    ...executionTargetSendFields(selection.executionTarget),
    ...(idempotencyKey ? { idempotency_key: idempotencyKey } : {}),
  };
}
