// The phone's Workspace choice (the phone must handle several Workspaces too): every Workspace the person
// can access (the bootstrap's list, as the desktop switch shows it) plus "All workspaces". The choice filters what the
// phone shows; the platform still checks every request against the person's own rights. Kept per phone (browser
// storage, a convenience only): a missing or unknown choice means all Workspaces.

export const ALL_WORKSPACES = "";
export const ALL_WORKSPACES_LABEL = "All workspaces";
const KEY = "octryx.m.workspace";

export type WorkspaceRef = { id: string; name: string; isDefault?: boolean; private?: boolean };

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem"> | null | undefined;

export function readWorkspaceChoice(store: Store): string {
  try {
    return store?.getItem(KEY) ?? ALL_WORKSPACES;
  } catch {
    return ALL_WORKSPACES;
  }
}

export function storeWorkspaceChoice(store: Store, workspaceId: string): void {
  try {
    if (workspaceId) store?.setItem(KEY, workspaceId);
    else store?.removeItem(KEY);
  } catch {
    // Private mode or blocked storage: the choice lasts until the app closes.
  }
}

/** The chosen Workspace when it is still one of the person's; otherwise all Workspaces. */
export function resolveWorkspace(choice: string, workspaces: WorkspaceRef[]): string {
  return choice && workspaces.some((workspace) => workspace.id === choice) ? choice : ALL_WORKSPACES;
}

/** Whether something of `projectId` shows under the choice; things without a Workspace show under every choice. */
export function inWorkspace(projectId: string | null | undefined, workspace: string): boolean {
  return !workspace || !projectId || projectId === workspace;
}

export function workspaceName(workspace: string, workspaces: WorkspaceRef[]): string {
  if (!workspace) return ALL_WORKSPACES_LABEL;
  return workspaces.find((item) => item.id === workspace)?.name ?? ALL_WORKSPACES_LABEL;
}

/** Where a new chat starts: the chosen Workspace, else the person's default, else the first one. */
export function newChatWorkspace(workspace: string, workspaces: WorkspaceRef[]): string {
  if (workspace && workspaces.some((item) => item.id === workspace)) return workspace;
  return workspaces.find((item) => item.isDefault)?.id ?? workspaces[0]?.id ?? "";
}

/** The Workspace whose budget the usage line shows: the chosen one, else the default, else the newest chat's. */
export function usageWorkspace(workspace: string, workspaces: WorkspaceRef[], newestChatWorkspace = ""): string {
  if (workspace) return workspace;
  return newestChatWorkspace || workspaces.find((item) => item.isDefault)?.id || workspaces[0]?.id || "";
}
