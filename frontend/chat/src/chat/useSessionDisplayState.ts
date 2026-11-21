import { useMemo } from "react";

import type { ChatState } from "../types";
import { shouldShowResumeNotice } from "./sessionStatusLabels";
import { summarizeTaskError } from "./appHelpers";
import { resolveBranding } from "./branding";

export function useSessionDisplayState({
  chatState,
  sending,
}: {
  chatState: ChatState | null;
  sending: boolean;
}) {
  const selectedSession = chatState?.selectedSession ?? null;
  const selectedSessionIsRunning = Boolean(chatState?.selectedSessionIsRunning);
  const activeBranding = resolveBranding(chatState?.branding);
  const currentUserName =
    chatState?.currentUser.displayName?.trim() ||
    chatState?.currentUser.username ||
    "User";
  const currentUserEmail =
    chatState?.currentUser.email?.trim() ||
    `${chatState?.currentUser.username || "user"}@workspace`;
  const composerDisabled = Boolean(
    chatState?.selectedSessionIsArchived || sending || selectedSessionIsRunning,
  );
  const taskErrorSummary = selectedSession?.taskError
    ? summarizeTaskError(selectedSession.taskError)
    : "";
  const selectedApprovals = useMemo(
    () => chatState?.selectedApprovals ?? [],
    [chatState?.selectedApprovals],
  );
  const selectedWorkspace = chatState?.selectedWorkspace ?? null;
  const showResumeNotice = shouldShowResumeNotice(
    selectedSession,
    selectedSessionIsRunning,
  );

  return {
    selectedSession,
    selectedSessionIsRunning,
    activeBranding,
    currentUserName,
    currentUserEmail,
    composerDisabled,
    taskErrorSummary,
    selectedApprovals,
    selectedWorkspace,
    showResumeNotice,
  };
}
