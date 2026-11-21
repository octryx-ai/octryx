// The view props of the app shell: the state, data, mode-of-work and action hook results wired to the view's names.

import { THINKING_OPTIONS } from "./appHelpers";
import type { useAppContainerActions } from "./useAppContainerActions";
import type { useAppContainerData } from "./useAppContainerData";
import type { useAppContainerState } from "./useAppContainerState";
import type { useAppContainerViewProps } from "./useAppContainerViewProps";
import type { useWorkflowSelection } from "./useWorkflowSelection";

type ViewArgs = Parameters<typeof useAppContainerViewProps>[0];

type ViewSources = {
  state: ReturnType<typeof useAppContainerState>;
  data: ReturnType<typeof useAppContainerData>;
  workflowSelection: ReturnType<typeof useWorkflowSelection>;
  actions: ReturnType<typeof useAppContainerActions>;
  // Values the app shell builds itself: area switches, the sidebar's thread list and the Workspace choice.
  shell: {
    setWorkspaceArea: ViewArgs["setActiveArea"];
    openSettingsTab: ViewArgs["openSettingsTab"];
    sidebarThreadGroups: ViewArgs["filteredThreadGroups"];
    threadBulk: ViewArgs["threadBulk"];
    handleLoadThreadGroupPage: ViewArgs["handleLoadThreadGroupPage"];
    handleProjectSelectionChange: ViewArgs["setSelectedProjectId"];
  };
};

function shellAndThreadArgs({ state, data, actions, shell }: ViewSources) {
  return {
    loading: state.loading,
    chatState: state.chatState,
    sidebarOpen: state.sidebarOpen,
    setSidebarOpen: state.setSidebarOpen,
    chatSidebarCollapsed: state.chatSidebarCollapsed,
    setChatSidebarCollapsed: state.setChatSidebarCollapsed,
    activeArea: state.activeArea,
    setActiveArea: shell.setWorkspaceArea,
    adminPanelInitialTab: state.adminPanelInitialTab,
    openSettingsTab: shell.openSettingsTab,
    activeBranding: data.activeBranding,
    filteredThreadGroups: shell.sidebarThreadGroups,
    handleThreadSelect: actions.handleThreadSelect,
    handleNewThread: actions.handleNewThread,
    threadSearchQuery: state.threadSearchQuery,
    setThreadSearchQuery: state.setThreadSearchQuery,
    currentUserName: data.currentUserName,
    currentUserEmail: data.currentUserEmail,
    profileDropdownOpen: state.profileDropdownOpen,
    setProfileDropdownOpen: state.setProfileDropdownOpen,
    handlePinThread: actions.handlePinThread,
    handleRenameThread: actions.handleRenameThread,
    handleExportThread: actions.handleExportThread,
    handleDeleteThread: actions.handleDeleteThread,
    handleLoadThreadGroupPage: shell.handleLoadThreadGroupPage,
    threadBulk: shell.threadBulk,
    canDeleteThreads: data.canDeleteThreads,
    workspacePanelOpen: state.workspacePanelOpen,
    selectedSession: data.selectedSession,
    selectedSessionProjectLabel: data.selectedSessionProjectLabel,
    selectedSessionRuntimePillLabel: data.selectedSessionRuntimePillLabel,
    runtimePillLabel: data.runtimePillLabel,
    threadStatusLabel: data.threadStatusLabel,
    statusLabel: data.statusLabel,
    modeLabel: data.modeLabel,
    selectedThinkingLevel: state.selectedThinkingLevel,
    chatTheme: state.chatTheme,
    setChatTheme: state.setChatTheme,
    statsOpen: state.statsOpen,
    setStatsOpen: state.setStatsOpen,
    selectedThreadCodeIntelligence: data.selectedThreadCodeIntelligence,
  };
}

function sessionAndComposerArgs({ state, data, actions }: ViewSources) {
  return {
    taskErrorSummary: data.taskErrorSummary,
    taskErrorOpen: state.taskErrorOpen,
    setTaskErrorOpen: state.setTaskErrorOpen,
    handleContinue: actions.handleContinue,
    setTraceOpen: state.setTraceOpen,
    setWorkspacePanelOpen: state.setWorkspacePanelOpen,
    renameOpen: state.renameOpen,
    handleRename: actions.handleRename,
    renameValue: state.renameValue,
    setRenameValue: state.setRenameValue,
    showCanvas: data.showCanvas,
    activeTool: data.activeTool,
    setActiveTool: data.setActiveTool,
    activeColor: data.activeColor,
    setActiveColor: data.setActiveColor,
    setShowCanvas: data.setShowCanvas,
    canvasRef: data.canvasRef,
    canvasWsRef: data.canvasWsRef,
    isDrawingRef: data.isDrawingRef,
    lastPosRef: data.lastPosRef,
    drawElement: data.drawElement,
    clearCanvas: data.clearCanvas,
    error: state.error,
    selectedSessionIsRunning: data.selectedSessionIsRunning,
    showResumeNotice: data.showResumeNotice,
    handleLoadOlderMessages: data.handleLoadOlderMessages,
    loadingOlderMessages: data.loadingOlderMessages,
    displayTimeline: data.displayTimeline,
    timelineFollowKey: data.timelineFollowKey,
    projectPillLabel: data.projectPillLabel,
    allowGlobalProjectSelection: data.allowGlobalProjectSelection,
    agentName: data.agentName,
    referencedArtifactsByMessageId: data.referencedArtifactsByMessageId,
    sending: state.sending,
    handleSubmitMessageFeedback: actions.handleSubmitMessageFeedback,
    handleReuseMessage: actions.handleReuseMessage,
    handleEditMessage: actions.handleEditMessage,
    handleRetryFromMessage: actions.handleRetryFromMessage,
    handleRetryFromToolEvent: actions.handleRetryFromToolEvent,
    handleRetryPrompt: actions.handleRetryPrompt,
    handleWorkflowDecision: actions.handleWorkflowDecision,
  };
}

function routingAndRunArgs({ state, data, actions }: ViewSources) {
  return {
    setPreviewArtifact: state.setPreviewArtifact,
    loadTurnTrace: data.loadTurnTrace,
    assistantRetryPromptByMessageId: data.assistantRetryPromptByMessageId,
    composerDisabled: data.composerDisabled,
    approvalRetryPromptById: data.approvalRetryPromptById,
    handleApprovalDecision: actions.handleApprovalDecision,
    handleRetryFromApproval: actions.handleRetryFromApproval,
    handleRetryFromChangePreview: actions.handleRetryFromChangePreview,
    editingMessage: state.editingMessage,
    handleCancelEditMessage: actions.handleCancelEditMessage,
    generateTaskResult: state.generateTaskResult,
    setGenerateTaskResult: state.setGenerateTaskResult,
    composerDragActive: state.composerDragActive,
    setComposerDragActive: state.setComposerDragActive,
    fileInputRef: state.fileInputRef,
    uploadDraftFiles: actions.uploadDraftFiles,
    slashCommand: state.slashCommand,
    SLASH_COMMANDS: actions.SLASH_COMMANDS,
    handleSend: actions.handleSend,
    handleStop: actions.handleStop,
    setComposerValue: state.setComposerValue,
    setSlashCommand: state.setSlashCommand,
    atMention: state.atMention,
    routingOverridesEnabled: state.routingOverridesEnabled,
    setRoutingOverridesEnabled: state.setRoutingOverridesEnabled,
    setSelectedAgentId: state.setSelectedAgentId,
    setSelectedAgentGroupId: state.setSelectedAgentGroupId,
    agentGroups: data.agentGroups,
    selectedAgentGroupId: state.selectedAgentGroupId,
    selectedAgentId: state.selectedAgentId,
    handleAgentGroupChange: actions.handleAgentGroupChange,
    agentGroupPillLabel: data.agentGroupPillLabel,
    handleAgentSelection: actions.handleAgentSelection,
    agentPillLabel: data.agentPillLabel,
    filteredAgentOptions: data.filteredAgentOptions,
    handleSelectAtAgent: actions.handleSelectAtAgent,
    draftAttachments: state.draftAttachments,
    uploadingAttachments: state.uploadingAttachments,
    removeDraftAttachment: actions.removeDraftAttachment,
    textareaRef: state.textareaRef,
  };
}

function workspaceAndTraceArgs({ state, data, workflowSelection, actions, shell }: ViewSources) {
  return {
    composerValue: state.composerValue,
    handleComposerChange: actions.handleComposerChange,
    handleComposerKeyDown: actions.handleComposerKeyDown,
    selectedRuntimeTargetId: state.selectedRuntimeTargetId,
    setSelectedRuntimeTargetId: state.setSelectedRuntimeTargetId,
    selectedProjectId: state.selectedProjectId,
    setSelectedProjectId: shell.handleProjectSelectionChange,
    setSelectedThinkingLevel: state.setSelectedThinkingLevel,
    THINKING_OPTIONS,
    thinkingPillLabel: data.thinkingPillLabel,
    workflowOptions: workflowSelection.workflowOptions,
    selectedWorkflowKey: workflowSelection.selectedWorkflowKey,
    setSelectedWorkflowKey: workflowSelection.setSelectedWorkflowKey,
    workflowPillLabel: workflowSelection.workflowPillLabel,
    selectedWorkflowCapability: workflowSelection.selectedWorkflowCapability,
    activeWorkflowChipLabel: workflowSelection.activeWorkflowChipLabel,
    sttAvailable: data.sttAvailable,
    sttListening: data.sttListening,
    startSTT: data.startSTT,
    openCanvas: data.openCanvas,
    ttsEnabled: state.ttsEnabled,
    effectiveWorkspace: data.effectiveWorkspace,
    handleRefreshWorkspace: data.handleRefreshWorkspace,
    handleLoadWorkspaceDirectory: data.handleLoadWorkspaceDirectory,
    handleSearchWorkspace: data.handleSearchWorkspace,
    handleCreateWorkspaceFolder: data.handleCreateWorkspaceFolder,
    handleRenameWorkspacePath: data.handleRenameWorkspacePath,
    handleMoveWorkspacePaths: data.handleMoveWorkspacePaths,
    handleDeleteWorkspacePaths: data.handleDeleteWorkspacePaths,
    handleCleanWorkspace: data.handleCleanWorkspace,
    traceOpen: state.traceOpen,
    previewArtifact: state.previewArtifact,
    loadState: data.loadState,
    handleArchiveThreadById: actions.handleArchiveThread,
    handleArchive: actions.handleArchive,
  };
}

// The view's names in the order the view reads them; built in four parts.
export function appContainerViewArgs(sources: ViewSources): ViewArgs {
  return {
    ...shellAndThreadArgs(sources),
    ...sessionAndComposerArgs(sources),
    ...routingAndRunArgs(sources),
    ...workspaceAndTraceArgs(sources),
  };
}
