// Send and workflow-decision actions of the chat composer, as plain functions over the hook's inputs.
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import type { ChatState } from "../types";
import type { SelectedSession } from "../chatThreadTypes";
import type { DraftAttachment } from "./useComposerInteractions.types";
import { buildChatSearch } from "./appHelpers";
import { readJson } from "./chatApiClient";
import { buildChatSendBody } from "./chatSendPayload";
import { claimSend, draftSendKey, releaseSend, type SendGuard } from "./chatSendGuard";
import { adoptNewThreadTarget, readExecutionTarget } from "./devices/executionTarget";
import { postProposalAnswer } from "./workflowProposalAnswer";
import { isGenerateCommand, runGenerateCommand, type GenerateTaskResult } from "./chatGenerateCommands";
import type { buildWorkflowProposalDecision, MessageSendOptions } from "./run/workflowDecisionSend";

type LoadOptions = {
  preserveTrace?: boolean;
  silent?: boolean;
};

export type MessageSendArgs = {
  composerValue: string;
  setComposerValue: Dispatch<SetStateAction<string>>;
  draftAttachments: DraftAttachment[];
  setDraftAttachments: Dispatch<SetStateAction<DraftAttachment[]>>;
  editingMessage: { id: string; content: string } | null;
  setEditingMessage: Dispatch<
    SetStateAction<{ id: string; content: string } | null>
  >;
  selectedSession: SelectedSession | null;
  selectedProjectId: string;
  selectedRuntimeTargetId: string;
  selectedThinkingLevel: string;
  selectedAgentId: string;
  selectedWorkflowKey: string;
  routingOverridesEnabled: boolean;
  sending: boolean;
  setSending: Dispatch<SetStateAction<boolean>>;
  setPendingPrompt: Dispatch<SetStateAction<string | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setGenerateTaskResult: Dispatch<SetStateAction<GenerateTaskResult>>;
  composerHistory: string[];
  setComposerHistory: Dispatch<SetStateAction<string[]>>;
  setComposerHistoryIndex: Dispatch<SetStateAction<number>>;
  composerNavigationDraftRef: MutableRefObject<string>;
  composerDraftKey: string;
  chatHistoryStorageKey: string;
  applyState: (
    nextState: ChatState,
    search?: string,
    options?: LoadOptions,
  ) => void;
  /** Held in a ref by the caller: survives re-renders, claimed synchronously. */
  sendGuard: SendGuard;
};

export type WorkflowProposalDecision = NonNullable<ReturnType<typeof buildWorkflowProposalDecision>>;

function persistComposerHistory(args: MessageSendArgs, nextHistory: string[]) {
  args.setComposerHistory(nextHistory);
  window.localStorage.setItem(
    args.chatHistoryStorageKey,
    JSON.stringify(nextHistory.slice(0, 50)),
  );
}

function rememberSubmittedPrompt(args: MessageSendArgs, prompt: string) {
  const trimmed = prompt.trim();
  if (!trimmed) {
    return;
  }
  const nextHistory = [
    trimmed,
    ...args.composerHistory.filter((entry) => entry !== trimmed),
  ].slice(0, 50);
  persistComposerHistory(args, nextHistory);
  args.setComposerHistoryIndex(-1);
  args.composerNavigationDraftRef.current = "";
  window.localStorage.removeItem(args.composerDraftKey);
}

function withAttachments(prompt: string, draftAttachments: DraftAttachment[]): string {
  return draftAttachments.length > 0
    ? `${prompt}\n\nAttached workspace files:\n${draftAttachments
        .map(
          (file) =>
            `- ${file.relativePath} | path: ${file.path} (${file.mediaType}, ${file.sizeBytes} bytes)`,
        )
        .join(
          "\n",
        )}\nUse ingest_document_source for PDFs, Office files, images, and large documents before answering questions about them.`
    : prompt;
}

function postMessage(
  args: MessageSendArgs,
  promptWithAttachments: string,
  overridePrompt?: string,
  sendOptions?: MessageSendOptions,
): Promise<ChatState> {
  const { editingMessage, selectedSession, sendGuard } = args;
  return editingMessage && selectedSession && !overridePrompt
    ? readJson<ChatState>(
        `/chat/api/sessions/${selectedSession.id}/messages/${editingMessage.id}/rerun`,
        {
          method: "POST",
          body: JSON.stringify({
            prompt: promptWithAttachments,
          }),
        },
      )
    : readJson<ChatState>("/chat/api/send", {
        method: "POST",
        body: JSON.stringify(
          buildChatSendBody(
            promptWithAttachments,
            {
              sessionId: selectedSession?.id ?? "",
              projectId: args.selectedProjectId,
              runtimeTargetId: args.selectedRuntimeTargetId,
              thinkingLevel: args.selectedThinkingLevel,
              routingOverridesEnabled: args.routingOverridesEnabled,
              agentId: args.selectedAgentId,
              workflowKey: args.selectedWorkflowKey,
              executionTarget: readExecutionTarget(selectedSession?.id),
            },
            sendOptions,
            draftSendKey(sendGuard),
          ),
        ),
      });
}

function startSend(args: MessageSendArgs, prompt: string): boolean {
  if (!claimSend(args.sendGuard)) {
    return false;
  }
  args.setSending(true);
  args.setPendingPrompt(prompt);
  args.setComposerValue("");
  args.setError(null);
  args.setGenerateTaskResult(null);
  return true;
}

function failSend(args: MessageSendArgs, sendError: unknown, rawPrompt: string) {
  releaseSend(args.sendGuard, { delivered: false });
  args.setSending(false);
  args.setPendingPrompt(null);
  args.setError(
    sendError instanceof Error
      ? sendError.message
      : "Failed to send message",
  );
  args.setComposerValue(rawPrompt);
  window.localStorage.setItem(args.composerDraftKey, rawPrompt);
}

export async function sendMessage(
  args: MessageSendArgs,
  overridePrompt?: string,
  sendOptions?: MessageSendOptions,
) {
  const { draftAttachments, selectedSession, sendGuard } = args;
  const rawPrompt = overridePrompt ?? args.composerValue.trim();
  const prompt =
    rawPrompt ||
    (draftAttachments.length > 0
      ? "Please inspect the attached files and help with them."
      : "");
  if (!prompt || args.sending) {
    return;
  }

  if (isGenerateCommand(prompt)) {
    const { setSending, setComposerValue, setError, setGenerateTaskResult } = args;
    await runGenerateCommand(prompt, {
      selectedSession, setSending, setComposerValue, setError, setGenerateTaskResult,
    });
    return;
  }

  if (!startSend(args, prompt)) {
    return;
  }
  const promptWithAttachments = withAttachments(prompt, draftAttachments);
  rememberSubmittedPrompt(args, prompt);

  try {
    const nextState = await postMessage(args, promptWithAttachments, overridePrompt, sendOptions);
    releaseSend(sendGuard, { delivered: true });
    const search = buildChatSearch({
      sessionId: nextState.selectedSession?.id ?? null,
    });
    args.applyState(nextState, search, { preserveTrace: true });
    if (!selectedSession) adoptNewThreadTarget(nextState.selectedSession?.id);
    args.setDraftAttachments([]);
    args.setEditingMessage(null);
  } catch (sendError) {
    failSend(args, sendError, rawPrompt);
  }
}

// The server records the answer before it re-sends the message, so a
// repeated click is answered with the current state and never runs twice.
// "Other workflow…" is answered on its own picker: its refusal is thrown
// back in words (422, 409) instead of the chat's error line.
export async function answerWorkflowProposal(
  args: MessageSendArgs,
  decision: WorkflowProposalDecision,
  inline = false,
) {
  const { setSending, setError } = args;
  // Answered on its own card: no re-sent turn follows, and a refusal goes back to that card.
  const onCard = inline || decision.body.decision === "other";
  if (args.sending) {
    if (onCard) throw new Error("Wait until the chat has finished sending.");
    return;
  }
  setSending(true);
  setError(null);
  try {
    const nextState = await postProposalAnswer(decision.path, decision.body);
    const search = buildChatSearch({
      sessionId: nextState.selectedSession?.id ?? null,
    });
    args.applyState(nextState, search, { preserveTrace: true });
    if (onCard) setSending(false);
  } catch (decisionError) {
    setSending(false);
    const message = decisionError instanceof Error
      ? decisionError.message
      : "Failed to answer the workflow suggestion";
    if (onCard) throw new Error(message);
    setError(message);
  }
}
