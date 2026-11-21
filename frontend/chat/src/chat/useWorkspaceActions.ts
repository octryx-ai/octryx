import { useCallback, useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { ChatState } from "../types";
import {
  clearWorkspace,
  loadOlderMessages,
  loadWorkspaceDirectory,
  refreshWorkspace,
  searchWorkspace,
  workspaceMutations,
} from "./workspaceActionHelpers";

type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

type WorkspaceActionsArgs = {
  selectedSessionId: string | null;
  chatState: ChatState | null;
  setChatState: Dispatch<SetStateAction<ChatState | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  readJson: ReadJsonFn;
};

export function useWorkspaceActions({
  selectedSessionId,
  chatState,
  setChatState,
  setError,
  readJson,
}: WorkspaceActionsArgs) {
  const [loadingOlderMessages, setLoadingOlderMessages] = useState(false);

  const handleRefreshWorkspace = useCallback(
    async () => refreshWorkspace({ selectedSessionId, setChatState, readJson }),
    [readJson, selectedSessionId, setChatState],
  );

  const context = { selectedSessionId, setChatState, readJson };

  const handleLoadWorkspaceDirectory = async (relativePath: string) =>
    loadWorkspaceDirectory(context, relativePath);

  const handleSearchWorkspace = async (query: string) => searchWorkspace(context, query);

  useEffect(() => {
    if (!selectedSessionId) {
      clearWorkspace(setChatState);
      return;
    }
    void handleRefreshWorkspace().catch(() => {
      /* keep current workspace snapshot on transient fetch failures */
    });
  }, [handleRefreshWorkspace, selectedSessionId, setChatState]);

  const handleLoadOlderMessages = async () =>
    loadOlderMessages(context, chatState, loadingOlderMessages, setLoadingOlderMessages, setError);

  const {
    handleCreateWorkspaceFolder,
    handleRenameWorkspacePath,
    handleMoveWorkspacePaths,
    handleDeleteWorkspacePaths,
    handleCleanWorkspace,
  } = workspaceMutations(context, handleRefreshWorkspace);

  return {
    loadingOlderMessages,
    handleRefreshWorkspace,
    handleLoadWorkspaceDirectory,
    handleSearchWorkspace,
    handleLoadOlderMessages,
    handleCreateWorkspaceFolder,
    handleRenameWorkspacePath,
    handleMoveWorkspacePaths,
    handleDeleteWorkspacePaths,
    handleCleanWorkspace,
  };
}
