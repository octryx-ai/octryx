import { AppContainerView } from "./chat/AppContainerView";
import { useAppContainerEffects } from "./chat/useAppContainerEffects";
import { useAppContainerState } from "./chat/useAppContainerState";
import { useAppContainerActions } from "./chat/useAppContainerActions";
import { useAppContainerData } from "./chat/useAppContainerData";
import { useWorkflowSelection } from "./chat/useWorkflowSelection";
import { useAppContainerViewProps } from "./chat/useAppContainerViewProps";
import { appContainerViewArgs } from "./chat/appContainerViewArgs";
import { useNewChatWorkspaceId } from "./chat/useActiveWorkspace";
import { appAreaNavigation } from "./chat/appAreaNavigation";
import { useSidebarThreads } from "./chat/useSidebarThreads";
import { useChatProjectSelection } from "./chat/useChatProjectSelection";
import { CHAT_HISTORY_STORAGE_KEY, appContainerActionArgs, appContainerDataArgs, projectSelectionArgs } from "./chat/appContainerHookArgs";

const CHAT_THEME_STORAGE_KEY = "octryx-chat-theme";

// ── Admin Panel ───────────────────────────────────────────────────────────────

export function AppContainer() {
  const state = useAppContainerState({
    chatThemeStorageKey: CHAT_THEME_STORAGE_KEY,
    chatHistoryStorageKey: CHAT_HISTORY_STORAGE_KEY,
  });
  const { setWorkspaceArea, openSettingsTab } = appAreaNavigation({
    setActiveArea: state.setActiveArea,
    setAdminPanelInitialTab: state.setAdminPanelInitialTab,
    setProfileDropdownOpen: state.setProfileDropdownOpen,
    setSidebarOpen: state.setSidebarOpen,
  });
  const data = useAppContainerData(appContainerDataArgs(state));
  const workflowSelection = useWorkflowSelection({
    selectedSession: data.selectedSession,
    workspaceId: state.selectedProjectId,
  });
  // "New chat" starts in the active Workspace, never in the archived one the chat on screen may live in.
  const newChatProjectId = useNewChatWorkspaceId(state.chatState?.currentUser?.id, state.chatState?.projects ?? [],
    state.selectedProjectId, data.allowGlobalProjectSelection);
  const actions = useAppContainerActions(appContainerActionArgs({ state, data, workflowSelection, newChatProjectId }));
  const { sidebarThreadGroups, threadBulk, handleLoadThreadGroupPage } = useSidebarThreads({
    setChatState: state.setChatState,
    threadSearchQuery: state.threadSearchQuery,
    filteredThreadGroups: data.filteredThreadGroups,
    loadState: data.loadState,
    canDeleteThreads: data.canDeleteThreads,
    selectedSessionId: data.selectedSession?.id ?? null,
    newChatProjectId,
    selectedRuntimeTargetId: state.selectedRuntimeTargetId,
  });

  useAppContainerEffects({
    selectedSessionId: data.selectedSession?.id ?? null,
    chatTheme: state.chatTheme,
    chatThemeStorageKey: CHAT_THEME_STORAGE_KEY,
    setEditingMessage: state.setEditingMessage,
    setStatsOpen: state.setStatsOpen,
  });

  const handleProjectSelectionChange = useChatProjectSelection(projectSelectionArgs(state, data));

  const viewProps = useAppContainerViewProps(appContainerViewArgs({
    state, data, workflowSelection, actions,
    shell: { setWorkspaceArea, openSettingsTab, sidebarThreadGroups, threadBulk, handleLoadThreadGroupPage,
      handleProjectSelectionChange },
  }));

  return <AppContainerView {...viewProps} />;
}
