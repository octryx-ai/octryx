import { useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import type { ChatState } from "../types";
import type { SelectedSession } from "../chatThreadTypes";
import type { DraftAttachment } from "./useComposerInteractions.types";
import { useComposerInteractions } from "./useComposerInteractions";
import { createSendGuard } from "./chatSendGuard";
import { useMessageSend } from "./useMessageSend";
import { useSessionActions } from "./useSessionActions";
import { useThreadUiActions } from "./useThreadUiActions";

type LoadOptions = {
  preserveTrace?: boolean;
  silent?: boolean;
};

type GenerateTaskResult = {
  taskName: string;
  taskUrl: string;
} | null;

type AgentOption = {
  id: string;
  name: string;
  groupId: string;
};

type AtMentionState = {
  open: boolean;
  query: string;
  startPos: number;
};

type SlashCommandState = {
  open: boolean;
  query: string;
};

type UseAppContainerActionsArgs = {
  selectedSessionId: string | null;
  selectedSession: SelectedSession | null;
  selectedSessionIsRunning: boolean;
  selectedSessionIsArchived: boolean;
  selectedProjectId: string;
  selectedRuntimeTargetId: string;
  selectedThinkingLevel: string;
  selectedAgentId: string;
  selectedAgentGroupId: string;
  selectedWorkflowKey: string;
  routingOverridesEnabled: boolean;
  canDeleteThreads: boolean;
  renameValue: string;
  sending: boolean;
  composerValue: string;
  composerHistory: string[];
  composerHistoryIndex: number;
  draftAttachments: DraftAttachment[];
  editingMessage: { id: string; content: string } | null;
  atMention: AtMentionState;
  slashCommand: SlashCommandState;
  agentOptions: AgentOption[];
  composerDraftKey: string;
  chatHistoryStorageKey: string;
  loadState: (search?: string, options?: LoadOptions) => Promise<void>;
  applyState: (
    nextState: ChatState,
    search?: string,
    options?: LoadOptions,
  ) => void;
  setComposerValue: Dispatch<SetStateAction<string>>;
  setEditingMessage: Dispatch<
    SetStateAction<{ id: string; content: string } | null>
  >;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setSelectedAgentGroupId: Dispatch<SetStateAction<string>>;
  setRoutingOverridesEnabled: Dispatch<SetStateAction<boolean>>;
  setSelectedModeKey: Dispatch<SetStateAction<string>>;
  setRenameValue: Dispatch<SetStateAction<string>>;
  setRenameOpen: Dispatch<SetStateAction<boolean>>;
  // The composer's selection follows a thread switch the user starts.
  beginComposerThreadSwitch: (targetSessionId: string) => void;
  // The Workspace "New chat" opens a draft in (newChatWorkspaceId); the chat's own when not given.
  newChatProjectId?: string;
  setDraftAttachments: Dispatch<SetStateAction<DraftAttachment[]>>;
  setSending: Dispatch<SetStateAction<boolean>>;
  setPendingPrompt: Dispatch<SetStateAction<string | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setGenerateTaskResult: Dispatch<SetStateAction<GenerateTaskResult>>;
  setComposerHistory: Dispatch<SetStateAction<string[]>>;
  setComposerHistoryIndex: Dispatch<SetStateAction<number>>;
  setAtMention: Dispatch<SetStateAction<AtMentionState>>;
  setSlashCommand: Dispatch<SetStateAction<SlashCommandState>>;
  setUploadingAttachments: Dispatch<SetStateAction<boolean>>;
  textareaRef: MutableRefObject<HTMLTextAreaElement | null>;
  fileInputRef: MutableRefObject<HTMLInputElement | null>;
  composerNavigationDraftRef: MutableRefObject<string>;
  uploadingAttachments: boolean;
};

export function useAppContainerActions(args: UseAppContainerActionsArgs) {
  const { selectedProjectId, textareaRef, newChatProjectId } = args;
  const threadActions = useThreadUiActions({
    selectedSessionId: args.selectedSessionId,
    selectedProjectId: newChatProjectId ?? selectedProjectId,
    selectedRuntimeTargetId: args.selectedRuntimeTargetId,
    canDeleteThreads: args.canDeleteThreads,
    loadState: args.loadState,
    setSelectedAgentId: args.setSelectedAgentId,
    setSelectedAgentGroupId: args.setSelectedAgentGroupId,
    setRoutingOverridesEnabled: args.setRoutingOverridesEnabled,
    beginComposerThreadSwitch: args.beginComposerThreadSwitch,
    focusComposer: () => textareaRef.current?.focus(),
  });

  const sendGuard = useRef(createSendGuard()).current;
  const { handleSend, handleWorkflowDecision } = useMessageSend(messageSendArgs(args, sendGuard));

  const composerActions = useComposerInteractions(composerArgs(args, handleSend));

  const sessionActions = useSessionActions(sessionArgs(args, handleSend));

  return {
    ...threadActions,
    ...composerActions,
    ...sessionActions,
    handleSend,
    handleWorkflowDecision,
  };
}

function messageSendArgs(args: UseAppContainerActionsArgs, sendGuard: ReturnType<typeof createSendGuard>) {
  return {
    composerValue: args.composerValue,
    setComposerValue: args.setComposerValue,
    draftAttachments: args.draftAttachments,
    setDraftAttachments: args.setDraftAttachments,
    editingMessage: args.editingMessage,
    setEditingMessage: args.setEditingMessage,
    selectedSession: args.selectedSession,
    selectedProjectId: args.selectedProjectId,
    selectedRuntimeTargetId: args.selectedRuntimeTargetId,
    selectedThinkingLevel: args.selectedThinkingLevel,
    selectedAgentId: args.selectedAgentId,
    selectedWorkflowKey: args.selectedWorkflowKey,
    routingOverridesEnabled: args.routingOverridesEnabled,
    sending: args.sending,
    setSending: args.setSending,
    setPendingPrompt: args.setPendingPrompt,
    setError: args.setError,
    setGenerateTaskResult: args.setGenerateTaskResult,
    composerHistory: args.composerHistory,
    setComposerHistory: args.setComposerHistory,
    setComposerHistoryIndex: args.setComposerHistoryIndex,
    composerNavigationDraftRef: args.composerNavigationDraftRef,
    composerDraftKey: args.composerDraftKey,
    chatHistoryStorageKey: args.chatHistoryStorageKey,
    applyState: args.applyState,
    sendGuard,
  };
}

type HandleSend = ReturnType<typeof useMessageSend>["handleSend"];

function composerArgs(args: UseAppContainerActionsArgs, handleSend: HandleSend) {
  return {
    composerValue: args.composerValue,
    setComposerValue: args.setComposerValue,
    atMention: args.atMention,
    setAtMention: args.setAtMention,
    slashCommand: args.slashCommand,
    setSlashCommand: args.setSlashCommand,
    composerHistory: args.composerHistory,
    composerHistoryIndex: args.composerHistoryIndex,
    setComposerHistoryIndex: args.setComposerHistoryIndex,
    composerNavigationDraftRef: args.composerNavigationDraftRef,
    composerDraftKey: args.composerDraftKey,
    textareaRef: args.textareaRef,
    handleSend,
    setEditingMessage: args.setEditingMessage,
    agentOptions: args.agentOptions,
    selectedAgentId: args.selectedAgentId,
    setSelectedAgentId: args.setSelectedAgentId,
    setSelectedModeKey: args.setSelectedModeKey,
    setSelectedAgentGroupId: args.setSelectedAgentGroupId,
    setRoutingOverridesEnabled: args.setRoutingOverridesEnabled,
    uploadingAttachments: args.uploadingAttachments,
    setUploadingAttachments: args.setUploadingAttachments,
    setError: args.setError,
    selectedSessionId: args.selectedSessionId,
    setDraftAttachments: args.setDraftAttachments,
    fileInputRef: args.fileInputRef,
  };
}

function sessionArgs(args: UseAppContainerActionsArgs, handleSend: HandleSend) {
  return {
    selectedSession: args.selectedSession,
    selectedSessionIsRunning: args.selectedSessionIsRunning,
    selectedSessionIsArchived: args.selectedSessionIsArchived,
    selectedProjectId: args.selectedProjectId,
    selectedRuntimeTargetId: args.selectedRuntimeTargetId,
    selectedThinkingLevel: args.selectedThinkingLevel,
    selectedAgentId: args.selectedAgentId,
    renameValue: args.renameValue,
    sending: args.sending,
    setSending: args.setSending,
    setEditingMessage: args.setEditingMessage,
    setError: args.setError,
    setGenerateTaskResult: args.setGenerateTaskResult,
    setPendingPrompt: args.setPendingPrompt,
    setDraftAttachments: args.setDraftAttachments,
    setComposerValue: args.setComposerValue,
    applyState: args.applyState,
    loadState: args.loadState,
    handleSend,
  };
}
