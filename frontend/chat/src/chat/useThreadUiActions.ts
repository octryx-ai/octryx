import { readJson } from "./chatApiClient";
import { useThreadSidebarActions } from "./useThreadSidebarActions";

export function useThreadUiActions({
  selectedSessionId,
  selectedProjectId,
  selectedRuntimeTargetId,
  canDeleteThreads,
  loadState,
  setSelectedAgentId,
  setSelectedAgentGroupId,
  setRoutingOverridesEnabled,
  beginComposerThreadSwitch,
  focusComposer,
}: {
  selectedSessionId: string | null;
  selectedProjectId: string;
  selectedRuntimeTargetId: string;
  canDeleteThreads: boolean;
  loadState: (
    search?: string,
    options?: { preserveTrace?: boolean; silent?: boolean },
  ) => Promise<void>;
  setSelectedAgentId: (value: string) => void;
  setSelectedAgentGroupId: (value: string) => void;
  setRoutingOverridesEnabled: (enabled: boolean) => void;
  beginComposerThreadSwitch?: (targetSessionId: string) => void;
  focusComposer?: () => void;
}) {
  const {
    handleThreadSelect,
    handleNewThread,
    handlePinThread,
    handleRenameThread,
    handleExportThread,
    handleExportAnalysisThread,
    handleDeleteThread,
  } = useThreadSidebarActions({
    selectedSessionId,
    selectedProjectId,
    selectedRuntimeTargetId,
    canDeleteThreads,
    readJson,
    loadState,
    beginComposerThreadSwitch,
    focusComposer,
    prepareNewThread: () => {
      setSelectedAgentId("");
      setSelectedAgentGroupId("");
      setRoutingOverridesEnabled(false);
    },
  });

  return {
    handleThreadSelect,
    handleNewThread,
    handlePinThread,
    handleRenameThread,
    handleExportThread,
    handleExportAnalysisThread,
    handleDeleteThread,
  };
}
