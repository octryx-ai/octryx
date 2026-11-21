import { useState } from "react";
import type { ChatState } from "../types";
import type { ThreadGroup } from "../chatThreadTypes";
import { readAllWorkspaces, scopeThreadGroups, threadScopeProjectId, writeAllWorkspaces } from "./threadScope";

function browserStore(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

// The chat list's Workspace scope for SidebarShell: the shown groups and the props of its "All workspaces" switch.
export function useThreadScope(chatState: ChatState | null, groups: ThreadGroup[]) {
  const userId = chatState?.currentUser?.id;
  const [allWorkspaces, setAllWorkspaces] = useState(() => readAllWorkspaces(browserStore(), userId));
  const activeProjectId = threadScopeProjectId(chatState?.selectedSession?.projectId, chatState?.selectedProjectId);
  const scope = scopeThreadGroups(groups, activeProjectId, allWorkspaces);
  const workspaceName = (chatState?.projects ?? []).find((project) => project.id === activeProjectId)?.name ?? "";
  return {
    ...scope,
    activeProjectId,
    toggle: {
      allWorkspaces,
      hiddenChats: scope.hiddenChats,
      hiddenWorkspaces: scope.hiddenWorkspaces,
      workspaceName,
      onChange: (next: boolean) => {
        setAllWorkspaces(next);
        writeAllWorkspaces(browserStore(), userId, next);
      },
    },
  };
}
