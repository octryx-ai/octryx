import type { ChatState } from "../types";
import { mergeThreadGroupPages } from "./threadGroupPages";

export function mergeBootstrapState({
  nextState,
  previousState,
}: {
  nextState: ChatState;
  previousState: ChatState | null;
}): ChatState {
  const nextSessionId = nextState.selectedSession?.id || null;
  const currentSessionId = previousState?.selectedSession?.id || null;
  const nextSelectedMessages = nextState.selectedMessages ?? [];
  const currentSelectedMessages = previousState?.selectedMessages ?? [];
  const nextSelectedMessageIds = new Set(
    nextSelectedMessages.map((message) => message.id),
  );
  const preservedOlderMessages =
    nextSessionId &&
    nextSessionId === currentSessionId &&
    currentSelectedMessages.length > nextSelectedMessages.length
      ? currentSelectedMessages.filter(
          (message) => !nextSelectedMessageIds.has(message.id),
        )
      : [];

  return {
    ...(previousState ?? ({} as ChatState)),
    ...nextState,
    // Session-scoped: a response without guidance must not keep another session's.
    chatAgentGuidance: nextState.chatAgentGuidance ?? null,
    // null: the answer does not include the list (an acknowledgement); [] clears it.
    activeThreadGroups: mergeThreadGroupPages(
      previousState?.activeThreadGroups,
      nextState.activeThreadGroups,
    ),
    archivedThreads:
      nextState.archivedThreads != null
        ? nextState.archivedThreads
        : (previousState?.archivedThreads ?? []),
    archivedThreadCount:
      nextState.archivedThreadCount != null
        ? nextState.archivedThreadCount
        : (previousState?.archivedThreadCount ?? 0),
    runtimeOptions:
      nextState.runtimeOptions && nextState.runtimeOptions.length > 0
        ? nextState.runtimeOptions
        : (previousState?.runtimeOptions ?? []),
    projects:
      nextState.projects && nextState.projects.length > 0
        ? nextState.projects
        : (previousState?.projects ?? []),
    agentOptions:
      nextState.agentOptions && nextState.agentOptions.length > 0
        ? nextState.agentOptions
        : (previousState?.agentOptions ?? []),
    agentGroups:
      nextState.agentGroups && nextState.agentGroups.length > 0
        ? nextState.agentGroups
        : (previousState?.agentGroups ?? []),
    agentModes:
      nextState.agentModes && nextState.agentModes.length > 0
        ? nextState.agentModes
        : (previousState?.agentModes ?? []),
    selectedMessages:
      nextState.selectedMessages !== undefined
        ? [...preservedOlderMessages, ...nextSelectedMessages]
        : currentSelectedMessages,
    selectedMessagesHasMore:
      nextState.selectedMessagesHasMore !== undefined
        ? preservedOlderMessages.length > 0
          ? (previousState?.selectedMessagesHasMore ??
            nextState.selectedMessagesHasMore)
          : nextState.selectedMessagesHasMore
        : nextSessionId && nextSessionId === currentSessionId
          ? (previousState?.selectedMessagesHasMore ?? false)
          : false,
    selectedWorkspace:
      nextState.selectedWorkspace !== undefined
        ? nextState.selectedWorkspace
        : nextSessionId && nextSessionId === currentSessionId
          ? (previousState?.selectedWorkspace ?? null)
          : null,
  };
}
