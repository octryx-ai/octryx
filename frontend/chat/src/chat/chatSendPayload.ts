// The body of POST /chat/api/send. The request has no mode field: the
// workflow's capability class and the platform decide. An agent reaches the
// server only through an explicit choice (an @mention), and a workflow only
// through the workflow selection; the default is Automatic (`workflow_key` "").

import { workflowDecisionsBody, type MessageSendOptions } from "./run/workflowDecisionSend";
import { executionTargetSendFields, type ExecutionTarget } from "./devices/executionTarget";

export type ChatSendSelection = {
  sessionId: string;
  projectId: string;
  runtimeTargetId: string;
  thinkingLevel: string;
  // True only after an explicit agent choice in the composer.
  routingOverridesEnabled: boolean;
  agentId: string;
  workflowKey: string;
  // A device target sends `execution_target` and blanks the Server-only selections.
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
