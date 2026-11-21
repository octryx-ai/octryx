// Request and state-merge steps behind the chat workspace actions.
import type { Dispatch, SetStateAction } from "react";

import type { ChatMessage } from "../chatThreadTypes";
import type { ChatState } from "../types";
import type { SelectedWorkspace } from "../chatWorkspaceTypes";

type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

export type WorkspaceActionContext = {
  selectedSessionId: string | null;
  setChatState: Dispatch<SetStateAction<ChatState | null>>;
  readJson: ReadJsonFn;
};

export function clearWorkspace(setChatState: WorkspaceActionContext["setChatState"]) {
  setChatState((current) =>
    current
      ? {
          ...current,
          selectedWorkspace: null,
        }
      : current,
  );
}

export async function refreshWorkspace({ selectedSessionId, setChatState, readJson }: WorkspaceActionContext) {
  if (!selectedSessionId) {
    clearWorkspace(setChatState);
    return;
  }
  const nextWorkspace = await readJson<SelectedWorkspace>(
    `/chat/api/sessions/${selectedSessionId}/workspace`,
  );
  setChatState((current) =>
    current
      ? {
          ...current,
          selectedWorkspace: nextWorkspace,
        }
      : current,
  );
}

export async function loadWorkspaceDirectory(
  { selectedSessionId, setChatState, readJson }: WorkspaceActionContext,
  relativePath: string,
) {
  if (!selectedSessionId) {
    return;
  }
  const normalizedPath = relativePath.trim();
  const payload = await readJson<{
    path: string;
    files: SelectedWorkspace["files"];
  }>(
    `/chat/api/sessions/${selectedSessionId}/workspace/tree?path=${encodeURIComponent(normalizedPath)}`,
  );
  setChatState((current) => {
    if (!current || current.selectedSession?.id !== selectedSessionId) {
      return current;
    }
    const existingFiles = current.selectedWorkspace?.files ?? [];
    const filteredFiles = existingFiles.filter(
      (entry) => entry.parentPath !== normalizedPath,
    );
    return {
      ...current,
      selectedWorkspace: {
        rootLabel: current.selectedWorkspace?.rootLabel || "Working Files",
        rootPath: current.selectedWorkspace?.rootPath || "",
        isTemporary: current.selectedWorkspace?.isTemporary ?? true,
        files: [...filteredFiles, ...payload.files],
        loadedDirectories: Array.from(
          new Set([
            ...(current.selectedWorkspace?.loadedDirectories ?? [""]),
            normalizedPath,
          ]),
        ),
        changes: current.selectedWorkspace?.changes ?? [],
      },
    };
  });
}

export async function searchWorkspace({ selectedSessionId, readJson }: WorkspaceActionContext, query: string) {
  if (!selectedSessionId) {
    return [];
  }
  const payload = await readJson<{
    query: string;
    files: SelectedWorkspace["files"];
  }>(
    `/chat/api/sessions/${selectedSessionId}/workspace/search?q=${encodeURIComponent(query)}`,
  );
  return payload.files;
}

function prependOlderMessages(
  current: ChatState | null,
  selectedSessionId: string,
  payload: { messages: ChatMessage[]; hasMore: boolean },
): ChatState | null {
  if (!current || current.selectedSession?.id !== selectedSessionId) {
    return current;
  }
  const existingIds = new Set(
    (current.selectedMessages ?? []).map((message) => message.id),
  );
  const olderMessages = payload.messages.filter(
    (message) => !existingIds.has(message.id),
  );
  return {
    ...current,
    selectedMessages: [
      ...olderMessages,
      ...(current.selectedMessages ?? []),
    ],
    selectedMessagesHasMore: payload.hasMore,
  };
}

export async function loadOlderMessages(
  { selectedSessionId, setChatState, readJson }: WorkspaceActionContext,
  chatState: ChatState | null,
  loadingOlderMessages: boolean,
  setLoadingOlderMessages: Dispatch<SetStateAction<boolean>>,
  setError: Dispatch<SetStateAction<string | null>>,
) {
  if (
    !selectedSessionId ||
    loadingOlderMessages ||
    !chatState?.selectedMessagesHasMore
  ) {
    return;
  }
  const oldestMessageId = chatState.selectedMessages[0]?.id;
  if (!oldestMessageId) {
    return;
  }
  setLoadingOlderMessages(true);
  try {
    const payload = await readJson<{
      messages: ChatMessage[];
      hasMore: boolean;
    }>(
      `/chat/api/sessions/${selectedSessionId}/messages?before_message_id=${encodeURIComponent(oldestMessageId)}`,
    );
    setChatState((current) => prependOlderMessages(current, selectedSessionId, payload));
  } catch (loadError) {
    setError(
      loadError instanceof Error
        ? loadError.message
        : "Failed to load older messages",
    );
  } finally {
    setLoadingOlderMessages(false);
  }
}

/** One workspace change request (folders, rename, move, delete, clean), then the tree reloads. */
export async function changeWorkspace(
  { selectedSessionId, readJson }: WorkspaceActionContext,
  endpoint: string,
  body: Record<string, unknown>,
  refresh: () => Promise<void>,
) {
  if (!selectedSessionId) {
    return;
  }
  await readJson<unknown>(
    `/chat/api/sessions/${selectedSessionId}/workspace/${endpoint}`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
  await refresh();
}

/** The tree-changing actions of the workspace panel; each reloads the tree when done. */
export function workspaceMutations(context: WorkspaceActionContext, refresh: () => Promise<void>) {
  return {
    handleCreateWorkspaceFolder: async (path: string) =>
      changeWorkspace(context, "folders", { path }, refresh),
    handleRenameWorkspacePath: async (path: string, newName: string) =>
      changeWorkspace(context, "rename", { path, new_name: newName }, refresh),
    handleMoveWorkspacePaths: async (paths: string[], targetDirectory: string) =>
      changeWorkspace(context, "move", { paths, target_directory: targetDirectory }, refresh),
    handleDeleteWorkspacePaths: async (paths: string[]) =>
      changeWorkspace(context, "delete", { paths }, refresh),
    handleCleanWorkspace: async () =>
      changeWorkspace(context, "clean", {}, refresh),
  };
}
