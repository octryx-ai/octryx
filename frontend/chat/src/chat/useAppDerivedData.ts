import { useMemo } from "react";

import type { ApprovalSummary } from "../chatDecisionTypes";
import type { ChatState } from "../types";
import type { SelectedWorkspace } from "../chatWorkspaceTypes";
import { aggregateThreadCodeIntelligence } from "./codeIntelligenceMetrics";
import { collectReferencedArtifactsByMessage } from "./appHelpers";
import {
  buildApprovalRetryPrompts,
  buildAssistantRetryPrompts,
  buildDisplayMessages,
  buildDisplayTimeline,
  buildEffectiveWorkspace,
  filterThreadGroups,
  timelineFollowKeyOf,
} from "./appDerivedDataHelpers";

function useDisplayTimeline(
  chatState: ChatState | null,
  pendingPrompt: string | null,
  selectedSessionIsRunning: boolean,
  streamActivityMessage: string | null,
  selectedApprovals: ApprovalSummary[],
) {
  const displayMessages = useMemo(
    () =>
      buildDisplayMessages(
        chatState?.selectedMessages ?? [],
        chatState?.selectedRuntimeLabel,
        pendingPrompt,
        selectedSessionIsRunning,
        streamActivityMessage,
      ),
    [
      chatState?.selectedMessages,
      chatState?.selectedRuntimeLabel,
      pendingPrompt,
      selectedSessionIsRunning,
      streamActivityMessage,
    ],
  );

  const displayTimeline = useMemo(
    () => buildDisplayTimeline(displayMessages, selectedApprovals),
    [displayMessages, selectedApprovals],
  );

  const timelineFollowKey = useMemo(() => timelineFollowKeyOf(displayTimeline), [displayTimeline]);

  return { displayMessages, displayTimeline, timelineFollowKey };
}

type AppDerivedDataArgs = {
  chatState: ChatState | null;
  threadSearchQuery: string;
  pendingPrompt: string | null;
  selectedSessionIsRunning: boolean;
  streamActivityMessage: string | null;
  selectedApprovals: ApprovalSummary[];
  selectedWorkspace: SelectedWorkspace | null;
};

export function useAppDerivedData({
  chatState,
  threadSearchQuery,
  pendingPrompt,
  selectedSessionIsRunning,
  streamActivityMessage,
  selectedApprovals,
  selectedWorkspace,
}: AppDerivedDataArgs) {
  const filteredThreadGroups = useMemo(
    () => filterThreadGroups(chatState?.activeThreadGroups ?? [], threadSearchQuery),
    [chatState?.activeThreadGroups, threadSearchQuery],
  );

  const { displayMessages, displayTimeline, timelineFollowKey } = useDisplayTimeline(
    chatState, pendingPrompt, selectedSessionIsRunning, streamActivityMessage, selectedApprovals);

  const referencedArtifactsByMessageId = useMemo(
    () =>
      collectReferencedArtifactsByMessage(chatState?.selectedMessages ?? []),
    [chatState?.selectedMessages],
  );

  const effectiveWorkspace = useMemo(
    () => buildEffectiveWorkspace(chatState?.selectedMessages ?? [], selectedApprovals, selectedWorkspace),
    [chatState?.selectedMessages, selectedApprovals, selectedWorkspace],
  );

  const assistantRetryPromptByMessageId = useMemo(
    () => buildAssistantRetryPrompts(chatState?.selectedMessages ?? []),
    [chatState?.selectedMessages],
  );

  const approvalRetryPromptById = useMemo(
    () => buildApprovalRetryPrompts(chatState?.selectedMessages ?? [], selectedApprovals),
    [chatState?.selectedMessages, selectedApprovals],
  );

  const selectedThreadCodeIntelligence = useMemo(
    () => aggregateThreadCodeIntelligence(chatState?.selectedMessages ?? []),
    [chatState?.selectedMessages],
  );

  return {
    filteredThreadGroups,
    displayMessages,
    displayTimeline,
    timelineFollowKey,
    referencedArtifactsByMessageId,
    effectiveWorkspace,
    assistantRetryPromptByMessageId,
    approvalRetryPromptById,
    selectedThreadCodeIntelligence,
  };
}
