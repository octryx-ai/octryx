import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import type { ChatState } from "../types";
import type { DraftAttachment } from "./useComposerInteractions.types";
import { readJson } from "./chatApiClient";
import { useAppDerivedData } from "./useAppDerivedData";
import { useCanvasRuntime } from "./useCanvasRuntime";
import { useChatBootstrapState } from "./useChatBootstrapState";
import { useComposerDraftLifecycle } from "./useComposerDraftLifecycle";
import { useRoutingPresentation } from "./useRoutingPresentation";
import { useSessionDisplayState } from "./useSessionDisplayState";
import { useSessionStream } from "./useSessionStream";
import { useSttInput } from "./useSttInput";
import { useWorkspaceActions } from "./useWorkspaceActions";

type UseAppContainerDataArgs = {
  chatState: ChatState | null;
  sending: boolean;
  routingOverridesEnabled: boolean;
  selectedProjectId: string;
  selectedRuntimeTargetId: string;
  selectedThinkingLevel: string;
  selectedAgentGroupId: string;
  selectedAgentId: string;
  selectedModeKey: string;
  threadSearchQuery: string;
  pendingPrompt: string | null;
  composerValue: string;
  setChatState: Dispatch<SetStateAction<ChatState | null>>;
  setComposerValue: Dispatch<SetStateAction<string>>;
  setSelectedProjectId: Dispatch<SetStateAction<string>>;
  setSelectedRuntimeTargetId: Dispatch<SetStateAction<string>>;
  setSelectedThinkingLevel: Dispatch<SetStateAction<string>>;
  setSelectedAgentGroupId: Dispatch<SetStateAction<string>>;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setSelectedModeKey: Dispatch<SetStateAction<string>>;
  setRoutingOverridesEnabled: Dispatch<SetStateAction<boolean>>;
  setRenameValue: Dispatch<SetStateAction<string>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setLoading: Dispatch<SetStateAction<boolean>>;
  setSending: Dispatch<SetStateAction<boolean>>;
  setPendingPrompt: Dispatch<SetStateAction<string | null>>;
  setRenameOpen: Dispatch<SetStateAction<boolean>>;
  setSidebarOpen: Dispatch<SetStateAction<boolean>>;
  setStatsOpen: Dispatch<SetStateAction<boolean>>;
  setTaskErrorOpen: Dispatch<SetStateAction<boolean>>;
  setTraceOpen: Dispatch<SetStateAction<boolean>>;
  setTtsEnabled: Dispatch<SetStateAction<boolean>>;
  setDraftAttachments: Dispatch<SetStateAction<DraftAttachment[]>>;
  setComposerHistoryIndex: Dispatch<SetStateAction<number>>;
  composerNavigationDraftRef: MutableRefObject<string>;
  textareaRef: MutableRefObject<HTMLTextAreaElement | null>;
};

export function useAppContainerData(args: UseAppContainerDataArgs) {
  const { chatState, sending, setComposerValue } = args;
  const { sttAvailable, sttListening, startSTT } = useSttInput({
    readJson,
    appendComposerText: (text) => {
      setComposerValue((current) => (current ? `${current} ${text}` : text));
    },
  });

  const display = useSessionDisplayState({
    chatState,
    sending,
  });
  const { selectedSession, selectedSessionIsRunning } = display;

  const { applyState, loadState, loadTurnTrace } = useChatBootstrapState(bootstrapSetters(args));

  const { streamActivityMessage } = useSessionStream({
    selectedSessionId: selectedSession?.id ?? null,
    streamToken: selectedSession?.streamToken ?? null,
    selectedSessionIsArchived: Boolean(chatState?.selectedSessionIsArchived),
    selectedSessionIsRunning,
    loadState,
  });

  const { canvasRuntime, workspaceActions, derivedData, composerDraftKey, routingPresentation } =
    useSessionWorkData(args, display, streamActivityMessage);

  return {
    sttAvailable,
    sttListening,
    startSTT,
    selectedSession,
    selectedSessionIsRunning,
    activeBranding: display.activeBranding,
    currentUserName: display.currentUserName,
    currentUserEmail: display.currentUserEmail,
    composerDisabled: display.composerDisabled,
    taskErrorSummary: display.taskErrorSummary,
    showResumeNotice: display.showResumeNotice,
    applyState,
    loadState,
    loadTurnTrace,
    composerDraftKey,
    ...canvasRuntime,
    ...workspaceActions,
    ...derivedData,
    ...routingPresentation,
  };
}

function bootstrapSetters(args: UseAppContainerDataArgs) {
  return {
    chatState: args.chatState,
    setChatState: args.setChatState,
    setSelectedProjectId: args.setSelectedProjectId,
    setSelectedRuntimeTargetId: args.setSelectedRuntimeTargetId,
    setSelectedThinkingLevel: args.setSelectedThinkingLevel,
    setSelectedAgentGroupId: args.setSelectedAgentGroupId,
    setSelectedAgentId: args.setSelectedAgentId,
    setSelectedModeKey: args.setSelectedModeKey,
    setRoutingOverridesEnabled: args.setRoutingOverridesEnabled,
    setRenameValue: args.setRenameValue,
    setError: args.setError,
    setLoading: args.setLoading,
    setSending: args.setSending,
    setPendingPrompt: args.setPendingPrompt,
    setRenameOpen: args.setRenameOpen,
    setSidebarOpen: args.setSidebarOpen,
    setStatsOpen: args.setStatsOpen,
    setTaskErrorOpen: args.setTaskErrorOpen,
    setTraceOpen: args.setTraceOpen,
    setTtsEnabled: args.setTtsEnabled,
  };
}

// The selected session's canvas, workspace actions, derived lists, composer draft and routing, in this hook order.
function useSessionWorkData(args: UseAppContainerDataArgs, display: ReturnType<typeof useSessionDisplayState>,
  streamActivityMessage: ReturnType<typeof useSessionStream>["streamActivityMessage"]) {
  const { chatState, setChatState, setError, selectedProjectId, selectedRuntimeTargetId, selectedModeKey } = args;
  const { selectedSession, selectedSessionIsRunning } = display;
  const canvasRuntime = useCanvasRuntime({
    selectedSessionId: selectedSession?.id ?? null,
    streamToken: selectedSession?.streamToken ?? null,
    readJson,
  });

  const workspaceActions = useWorkspaceActions({
    selectedSessionId: selectedSession?.id ?? null,
    chatState,
    setChatState,
    setError,
    readJson,
  });

  const derivedData = useAppDerivedData({
    chatState,
    threadSearchQuery: args.threadSearchQuery,
    pendingPrompt: args.pendingPrompt,
    selectedSessionIsRunning,
    streamActivityMessage,
    selectedApprovals: display.selectedApprovals,
    selectedWorkspace: display.selectedWorkspace,
  });

  const { composerDraftKey } = useComposerDraftLifecycle({
    selectedSessionId: selectedSession?.id ?? null,
    selectedProjectId,
    selectedRuntimeTargetId,
    selectedModeKey,
    composerValue: args.composerValue,
    setComposerValue: args.setComposerValue,
    setDraftAttachments: args.setDraftAttachments,
    setComposerHistoryIndex: args.setComposerHistoryIndex,
    composerNavigationDraftRef: args.composerNavigationDraftRef,
    textareaRef: args.textareaRef,
  });

  const routingPresentation = useRoutingPresentation({
    chatState,
    selectedSession,
    selectedRuntimeTargetId,
    selectedProjectId,
    selectedThinkingLevel: args.selectedThinkingLevel,
    selectedAgentId: args.selectedAgentId,
    selectedAgentGroupId: args.selectedAgentGroupId,
    selectedModeKey,
    selectedSessionIsRunning,
  });
  return { canvasRuntime, workspaceActions, derivedData, composerDraftKey, routingPresentation };
}
