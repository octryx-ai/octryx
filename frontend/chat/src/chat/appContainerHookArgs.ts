// The argument objects AppContainer hands to its data and action hooks, built from the container state.
import type { useAppContainerState } from "./useAppContainerState";
import type { useAppContainerActions } from "./useAppContainerActions";
import type { useAppContainerData } from "./useAppContainerData";
import type { useChatProjectSelection } from "./useChatProjectSelection";
import type { useWorkflowSelection } from "./useWorkflowSelection";

export const CHAT_HISTORY_STORAGE_KEY = "octryx-chat-composer-history";

type ContainerState = ReturnType<typeof useAppContainerState>;

export function appContainerDataArgs(state: ContainerState): Parameters<typeof useAppContainerData>[0] {
  return {
    chatState: state.chatState,
    sending: state.sending,
    routingOverridesEnabled: state.routingOverridesEnabled,
    selectedProjectId: state.selectedProjectId,
    selectedRuntimeTargetId: state.selectedRuntimeTargetId,
    selectedThinkingLevel: state.selectedThinkingLevel,
    selectedAgentGroupId: state.selectedAgentGroupId,
    selectedAgentId: state.selectedAgentId,
    selectedModeKey: state.selectedModeKey,
    threadSearchQuery: state.threadSearchQuery,
    pendingPrompt: state.pendingPrompt,
    composerValue: state.composerValue,
    setChatState: state.setChatState,
    setComposerValue: state.setComposerValue,
    setSelectedProjectId: state.setSelectedProjectId,
    setSelectedRuntimeTargetId: state.setSelectedRuntimeTargetId,
    setSelectedThinkingLevel: state.setSelectedThinkingLevel,
    setSelectedAgentGroupId: state.setSelectedAgentGroupId,
    setSelectedAgentId: state.setSelectedAgentId,
    setSelectedModeKey: state.setSelectedModeKey,
    setRoutingOverridesEnabled: state.setRoutingOverridesEnabled,
    setRenameValue: state.setRenameValue,
    setError: state.setError,
    setLoading: state.setLoading,
    setSending: state.setSending,
    setPendingPrompt: state.setPendingPrompt,
    setRenameOpen: state.setRenameOpen,
    setSidebarOpen: state.setSidebarOpen,
    setStatsOpen: state.setStatsOpen,
    setTaskErrorOpen: state.setTaskErrorOpen,
    setTraceOpen: state.setTraceOpen,
    setTtsEnabled: state.setTtsEnabled,
    setDraftAttachments: state.setDraftAttachments,
    setComposerHistoryIndex: state.setComposerHistoryIndex,
    composerNavigationDraftRef: state.composerNavigationDraftRef,
    textareaRef: state.textareaRef,
  };
}

type ActionSources = {
  state: ContainerState;
  data: ReturnType<typeof useAppContainerData>;
  workflowSelection: ReturnType<typeof useWorkflowSelection>;
  newChatProjectId: string;
};

export function appContainerActionArgs(sources: ActionSources): Parameters<typeof useAppContainerActions>[0] {
  return { ...actionValues(sources), ...actionSetters(sources) };
}

// What the actions read: the selection, the composer and the loaded data.
function actionValues({ state, data, workflowSelection, newChatProjectId }: ActionSources) {
  return {
    newChatProjectId,
    selectedSessionId: data.selectedSession?.id ?? null,
    selectedSession: data.selectedSession,
    selectedSessionIsRunning: data.selectedSessionIsRunning,
    selectedSessionIsArchived: Boolean(state.chatState?.selectedSessionIsArchived),
    selectedProjectId: state.selectedProjectId,
    selectedRuntimeTargetId: state.selectedRuntimeTargetId,
    selectedThinkingLevel: state.selectedThinkingLevel,
    selectedAgentId: state.selectedAgentId,
    selectedAgentGroupId: state.selectedAgentGroupId,
    selectedWorkflowKey: workflowSelection.selectedWorkflowKey,
    routingOverridesEnabled: state.routingOverridesEnabled,
    canDeleteThreads: data.canDeleteThreads,
    renameValue: state.renameValue,
    sending: state.sending,
    composerValue: state.composerValue,
    composerHistory: state.composerHistory,
    composerHistoryIndex: state.composerHistoryIndex,
    draftAttachments: state.draftAttachments,
    editingMessage: state.editingMessage,
    atMention: state.atMention,
    slashCommand: state.slashCommand,
    agentOptions: data.agentOptions,
    composerDraftKey: data.composerDraftKey,
    chatHistoryStorageKey: CHAT_HISTORY_STORAGE_KEY,
    loadState: data.loadState,
    applyState: data.applyState,
  };
}

// What the actions change: setters, refs and the thread switch.
function actionSetters({ state, workflowSelection }: ActionSources) {
  return {
    setComposerValue: state.setComposerValue,
    setEditingMessage: state.setEditingMessage,
    setSelectedAgentId: state.setSelectedAgentId,
    setSelectedAgentGroupId: state.setSelectedAgentGroupId,
    setRoutingOverridesEnabled: state.setRoutingOverridesEnabled,
    setSelectedModeKey: state.setSelectedModeKey,
    setRenameValue: state.setRenameValue,
    setRenameOpen: state.setRenameOpen,
    beginComposerThreadSwitch: workflowSelection.beginThreadSwitch,
    setDraftAttachments: state.setDraftAttachments,
    setSending: state.setSending,
    setPendingPrompt: state.setPendingPrompt,
    setError: state.setError,
    setGenerateTaskResult: state.setGenerateTaskResult,
    setComposerHistory: state.setComposerHistory,
    setComposerHistoryIndex: state.setComposerHistoryIndex,
    setAtMention: state.setAtMention,
    setSlashCommand: state.setSlashCommand,
    setUploadingAttachments: state.setUploadingAttachments,
    textareaRef: state.textareaRef,
    fileInputRef: state.fileInputRef,
    composerNavigationDraftRef: state.composerNavigationDraftRef,
    uploadingAttachments: state.uploadingAttachments,
  };
}

export function projectSelectionArgs(state: ContainerState, data: ReturnType<typeof useAppContainerData>):
  Parameters<typeof useChatProjectSelection>[0] {
  return {
    userId: state.chatState?.currentUser?.id,
    projects: state.chatState?.projects ?? [],
    selectedProjectId: state.selectedProjectId,
    setSelectedProjectId: state.setSelectedProjectId,
    setSelectedAgentGroupId: state.setSelectedAgentGroupId,
    setSelectedAgentId: state.setSelectedAgentId,
    setRoutingOverridesEnabled: state.setRoutingOverridesEnabled,
    hasSelectedSession: Boolean(data.selectedSession),
    allowGlobalProjectSelection: data.allowGlobalProjectSelection,
    chatVisible: state.activeArea === "chat",
    selectedRuntimeTargetId: state.selectedRuntimeTargetId,
    loadState: data.loadState,
  };
}
