// Session requests behind the session action handlers: archive, feedback, rename and approval.
import type { FormEvent } from "react";
import type { MessageFeedbackPayload } from "./messageFeedbackModel";

import type { ApprovalSummary } from "../chatDecisionTypes";
import type { ChatState } from "../types";
import { approvalDecisionErrorText } from "./approvalCardActions";
import { buildChatSearch } from "./appHelpers";
import { readJson } from "./chatApiClient";
import { emitTurnExecutionRefresh } from "./run/turnExecutionRefreshSignal";
import type { UseSessionActionsArgs } from "./useSessionActions.types";

type Args = UseSessionActionsArgs;

const errorText = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

export async function archiveSelectedSession(args: Args) {
  const { selectedSession } = args;
  if (!selectedSession) {
    return;
  }
  try {
    await readJson<{ ok: boolean }>(`/chat/api/sessions/${selectedSession.id}/archive`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    const search = buildChatSearch({
      newThread: true,
      projectId: args.selectedProjectId,
      runtimeTargetId: args.selectedRuntimeTargetId,
    });
    window.history.replaceState({}, "", `/chat${search}`);
    await args.loadState(search);
  } catch (archiveError) {
    args.setError(errorText(archiveError, "Failed to archive thread"));
  }
}

export function applyFeedbackState(args: Args, nextState: ChatState) {
  const search = buildChatSearch({
    sessionId: nextState.selectedSession?.id ?? args.selectedSession?.id ?? null,
    projectId: nextState.selectedProjectId,
    runtimeTargetId: nextState.selectedRuntimeTargetId,
    agentId: nextState.selectedAgentId,
    agentType: nextState.selectedAgentType,
  });
  args.applyState(nextState, search, { preserveTrace: true });
}

export async function submitMessageFeedback(args: Args, messageId: string, payload: MessageFeedbackPayload) {
  if (!args.selectedSession) {
    return;
  }
  const nextState = await readJson<ChatState>(
    `/chat/api/sessions/${args.selectedSession.id}/messages/${messageId}/feedback`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  applyFeedbackState(args, nextState);
}

export async function renameSession(args: Args, event: FormEvent) {
  event.preventDefault();
  if (!args.selectedSession) {
    return;
  }
  try {
    const nextState = await readJson<ChatState>(`/chat/api/sessions/${args.selectedSession.id}/rename`, {
      method: "POST",
      body: JSON.stringify({ title: args.renameValue }),
    });
    const search = buildChatSearch({ sessionId: nextState.selectedSession?.id ?? null });
    args.applyState(nextState, search, { preserveTrace: true });
  } catch (renameError) {
    args.setError(errorText(renameError, "Failed to rename thread"));
  }
}

// "always" records the standing rule (Workspace admin or owner), then approves the same record.
export async function decideApproval(
  args: Args,
  approval: ApprovalSummary,
  decision: "approve" | "reject" | "always",
) {
  const { selectedSession } = args;
  if (!selectedSession) {
    return;
  }
  try {
    const nextState = await readJson<ChatState>(`/chat/api/approvals/${approval.id}/${decision}`, { method: "POST" });
    const search = buildChatSearch({ sessionId: nextState.selectedSession?.id ?? selectedSession.id });
    args.applyState(nextState, search, { preserveTrace: true });
    emitTurnExecutionRefresh(selectedSession.id);
  } catch (decisionError) {
    const { status, code } = (decisionError ?? {}) as { status?: unknown; code?: unknown };
    args.setError(
      approvalDecisionErrorText(
        decision,
        typeof status === "number" ? status : null,
        decisionError instanceof Error ? decisionError.message : "",
        typeof code === "string" ? code : null,
      ),
    );
  }
}

export async function archiveThread(args: Args, threadId: string, onArchiveCurrent: () => Promise<void>) {
  if (args.selectedSession?.id === threadId) {
    await onArchiveCurrent();
    return;
  }
  await readJson<{ ok: boolean }>(`/chat/api/sessions/${threadId}/archive`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  await args.loadState(window.location.search, { preserveTrace: true, silent: true });
}
