import type { ThreadGroup } from "../chatThreadTypes";

// The chat list shows the active Workspace's chats. "All workspaces" is an explicit switch and
// remembered per person in this browser. The active Workspace is the open chat's own Workspace, else the composer's,
// so a link to a chat of another Workspace opens it in its own list.
export type ThreadScope = { groups: ThreadGroup[]; hiddenChats: number; hiddenWorkspaces: number; scoped: boolean };

const KEY = "octryx.chat.allWorkspaces.v1";

const chatsOf = (group: ThreadGroup) => group.totalThreadCount ?? group.sessions.length;

/** The groups the list shows; without an active Workspace, or with "All workspaces" on, every group. */
export function scopeThreadGroups(groups: ThreadGroup[], activeProjectId: string | null | undefined,
  allWorkspaces: boolean): ThreadScope {
  const active = (activeProjectId || "").trim();
  if (allWorkspaces || !active) return { groups, hiddenChats: 0, hiddenWorkspaces: 0, scoped: false };
  const shown = groups.filter((group) => (group.projectId ?? "") === active);
  const hidden = groups.filter((group) => (group.projectId ?? "") !== active);
  return {
    groups: shown,
    hiddenChats: hidden.reduce((total, group) => total + chatsOf(group), 0),
    hiddenWorkspaces: hidden.length,
    scoped: true,
  };
}

/** The Workspace the chat list follows: the open chat's, else the composer's. */
export function threadScopeProjectId(selectedSessionProjectId: string | null | undefined,
  selectedProjectId: string | null | undefined): string {
  return (selectedSessionProjectId || selectedProjectId || "").trim();
}

type Store = Pick<Storage, "getItem" | "setItem">;

export function readAllWorkspaces(store: Store | null, userId: string | null | undefined): boolean {
  if (!userId) return false;
  try {
    return store?.getItem(`${KEY}.${userId}`) === "on";
  } catch {
    return false;
  }
}

export function writeAllWorkspaces(store: Store | null, userId: string | null | undefined, on: boolean) {
  if (!userId) return;
  try {
    store?.setItem(`${KEY}.${userId}`, on ? "on" : "off");
  } catch {
    // Blocked storage: the switch simply resets on the next load.
  }
}
