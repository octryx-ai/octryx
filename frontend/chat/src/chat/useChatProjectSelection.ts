// The chat's Workspace choice: a change resets the agent picks and, on a new chat, reloads it for the Workspace.

import { buildChatSearch } from "./appHelpers";
import { useChatWorkspaceSync } from "./useActiveWorkspace";

type WorkspaceRef = Parameters<typeof useChatWorkspaceSync>[3][number];
type LoadState = (search: string) => Promise<unknown>;

export function useChatProjectSelection({
  userId,
  projects,
  selectedProjectId,
  setSelectedProjectId,
  setSelectedAgentGroupId,
  setSelectedAgentId,
  setRoutingOverridesEnabled,
  hasSelectedSession,
  allowGlobalProjectSelection,
  chatVisible,
  selectedRuntimeTargetId,
  loadState,
}: {
  userId: string | null | undefined;
  projects: WorkspaceRef[];
  selectedProjectId: string;
  setSelectedProjectId: (projectId: string) => void;
  setSelectedAgentGroupId: (id: string) => void;
  setSelectedAgentId: (id: string) => void;
  setRoutingOverridesEnabled: (enabled: boolean) => void;
  hasSelectedSession: boolean;
  allowGlobalProjectSelection: boolean;
  chatVisible: boolean;
  selectedRuntimeTargetId: string;
  loadState: LoadState;
}) {
  const handleProjectSelectionChange = (projectId: string) => {
    setSelectedProjectId(projectId);
    setSelectedAgentGroupId("");
    setSelectedAgentId("");
    setRoutingOverridesEnabled(false);
    if (!hasSelectedSession) {
      void loadState(
        buildChatSearch({
          newThread: true,
          projectId,
          runtimeTargetId: selectedRuntimeTargetId,
        }),
      );
    }
  };

  // A workspace chosen in another area carries over to a new, unstarted chat.
  useChatWorkspaceSync(userId, selectedProjectId, (projectId: string) => {
    setSelectedProjectId(projectId);
    setSelectedAgentGroupId("");
    setSelectedAgentId("");
  }, projects, hasSelectedSession, allowGlobalProjectSelection, chatVisible,
  (projectId: string) => {
    // Another Workspace chosen while an existing chat of a different one is on screen: a new chat there. For Global
    // ("", administrators) the new chat stays without a Workspace even where the bootstrap starts in the default one.
    const search = buildChatSearch({ newThread: true, projectId, runtimeTargetId: selectedRuntimeTargetId });
    window.history.pushState({}, "", `/chat${search}`);
    void loadState(search).then(() => { if (!projectId) setSelectedProjectId(""); });
  });

  return handleProjectSelectionChange;
}
