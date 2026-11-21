// Retry handlers of a chat session: send a prompt again, or rerun from a message, tool step, approval or change preview.
import type { ChatState } from "../types";
import { buildChatSearch } from "./appHelpers";
import { readJson } from "./chatApiClient";
import type { UseSessionActionsArgs } from "./useSessionActions.types";

export function createSessionRetryHandlers({
  selectedSession,
  sending,
  setSending,
  setEditingMessage,
  setError,
  setGenerateTaskResult,
  setPendingPrompt,
  setDraftAttachments,
  applyState,
  handleSend,
}: UseSessionActionsArgs) {
  const handleRetryPrompt = async (prompt: string) => {
    setEditingMessage(null);
    await handleSend(prompt);
  };

  const runRetryFrom = async ({
    endpoint,
    prompt,
    errorMessage,
  }: {
    endpoint: string;
    prompt: string;
    errorMessage: string;
  }) => {
    if (!selectedSession || sending) {
      return;
    }
    setEditingMessage(null);
    setSending(true);
    setPendingPrompt(prompt);
    setError(null);
    setGenerateTaskResult(null);
    try {
      const nextState = await readJson<ChatState>(endpoint, {
        method: "POST",
        body: JSON.stringify({ prompt }),
      });
      const search = buildChatSearch({
        sessionId: nextState.selectedSession?.id ?? selectedSession.id,
      });
      applyState(nextState, search, { preserveTrace: true });
      setDraftAttachments([]);
    } catch (retryError) {
      setSending(false);
      setPendingPrompt(null);
      setError(retryError instanceof Error ? retryError.message : errorMessage);
    }
  };

  const handleRetryFromMessage = async (messageId: string, prompt: string) => {
    await runRetryFrom({
      endpoint: `/chat/api/sessions/${selectedSession?.id || ""}/messages/${messageId}/rerun`,
      prompt,
      errorMessage: "Failed to retry from this point",
    });
  };

  const handleRetryFromToolEvent = async (
    toolCallId: string,
    prompt: string,
  ) => {
    await runRetryFrom({
      endpoint: `/chat/api/sessions/${selectedSession?.id || ""}/tool-calls/${toolCallId}/rerun`,
      prompt,
      errorMessage: "Failed to retry from this tool step",
    });
  };

  const handleRetryFromApproval = async (
    approvalId: string,
    prompt: string,
  ) => {
    await runRetryFrom({
      endpoint: `/chat/api/sessions/${selectedSession?.id || ""}/approvals/${approvalId}/rerun`,
      prompt,
      errorMessage: "Failed to retry from this approval",
    });
  };

  const handleRetryFromChangePreview = async (
    previewId: string,
    prompt: string,
  ) => {
    await runRetryFrom({
      endpoint: `/chat/api/sessions/${selectedSession?.id || ""}/change-previews/${previewId}/rerun`,
      prompt,
      errorMessage: "Failed to retry from this change preview",
    });
  };

  return {
    handleRetryPrompt,
    handleRetryFromMessage,
    handleRetryFromToolEvent,
    handleRetryFromApproval,
    handleRetryFromChangePreview,
  };
}
