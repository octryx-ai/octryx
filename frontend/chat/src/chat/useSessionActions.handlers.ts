// Session action handlers (archive, feedback, rename, approval); retry and stop/continue come from their modules.
import type { FormEvent } from "react";
import type { MessageFeedbackPayload } from "./messageFeedbackModel";

import type { ApprovalSummary } from "../chatDecisionTypes";
import { createSessionRetryHandlers } from "./useSessionActions.retry";
import { createSessionRunControlHandlers } from "./useSessionActions.runControl";
import {
  archiveSelectedSession,
  archiveThread,
  decideApproval,
  renameSession,
  submitMessageFeedback,
} from "./useSessionActions.session";
import type { UseSessionActionsArgs } from "./useSessionActions.types";

export function createSessionActionHandlers(args: UseSessionActionsArgs) {
  const {
    handleRetryPrompt,
    handleRetryFromMessage,
    handleRetryFromToolEvent,
    handleRetryFromApproval,
    handleRetryFromChangePreview,
  } = createSessionRetryHandlers(args);
  const { handleStop, handleContinue } = createSessionRunControlHandlers(args);
  const handleArchive = () => archiveSelectedSession(args);
  const handleSubmitMessageFeedback = (messageId: string, payload: MessageFeedbackPayload) =>
    submitMessageFeedback(args, messageId, payload);
  const handleRename = (event: FormEvent) => renameSession(args, event);
  const handleApprovalDecision = (approval: ApprovalSummary, decision: "approve" | "reject" | "always") =>
    decideApproval(args, approval, decision);
  const handleArchiveThread = (threadId: string, onArchiveCurrent: () => Promise<void>) =>
    archiveThread(args, threadId, onArchiveCurrent);

  return {
    handleRetryPrompt,
    handleRetryFromMessage,
    handleRetryFromToolEvent,
    handleRetryFromApproval,
    handleRetryFromChangePreview,
    handleArchive,
    handleStop,
    handleContinue,
    handleSubmitMessageFeedback,
    handleRename,
    handleApprovalDecision,
    handleArchiveThread,
  };
}
