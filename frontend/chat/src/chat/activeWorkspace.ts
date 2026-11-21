// One active workspace across Chat, Knowledge, Coding and the admin-shell
// areas. Precedence: explicit URL `workspace_id`, then the user's last explicit
// choice, then the chat's selected workspace. There is deliberately no "first
// project in the list" fallback: an unrelated or temporary workspace must never
// be preselected without intent. An explicit "no workspace" choice is kept as
// such and never silently replaced by the chat's workspace.
export const ACTIVE_WORKSPACE_EVENT = "octryx-active-workspace-change";
const STORAGE_PREFIX = "octryx-active-workspace";
const NO_WORKSPACE = "__none__";
type WorkspaceRef = { id: string };
// null: no preference yet; "": explicitly no workspace; otherwise a workspace id.
export type WorkspacePreference = string | null;

let storageUser = "";

// Preferences are per signed-in user, so a shared browser never reopens the
// previous user's workspace.
export function setActiveWorkspaceUser(userId: string | null | undefined) {
  storageUser = userId || "";
}

function storageKey() {
  return storageUser ? `${STORAGE_PREFIX}:${storageUser}` : "";
}

export function resolveActiveWorkspaceId(
  projects: WorkspaceRef[],
  preference: WorkspacePreference,
  fallbackId?: string | null,
): string {
  if (preference === "") return "";
  const known = new Set(projects.map((project) => project.id));
  if (preference && known.has(preference)) return preference;
  return fallbackId && known.has(fallbackId) ? fallbackId : "";
}

export function readStoredWorkspacePreference(): WorkspacePreference {
  return storedWorkspacePreferenceOf(storageUser);
}

// The stored choice of one user, readable before the bootstrap names the signed-in user (startupRequests.ts).
export function storedWorkspacePreferenceOf(userId: string): WorkspacePreference {
  const key = userId ? `${STORAGE_PREFIX}:${userId}` : "";
  if (!key) return null;
  try {
    const value = window.localStorage.getItem(key);
    if (value === null) return null;
    return value === NO_WORKSPACE ? "" : value;
  } catch {
    return null;
  }
}

export function readUrlWorkspaceId(search?: string): string {
  try {
    return new URLSearchParams(search ?? window.location.search).get("workspace_id") || "";
  } catch {
    return "";
  }
}

// The URL after an explicit choice: workspace_id follows the choice, and a
// source link that pointed into another workspace is not carried over.
export function hrefWithWorkspace(href: string, workspaceId: string): string {
  const url = new URL(href);
  const previous = url.searchParams.get("workspace_id");
  if (!previous && !workspaceId) return url.toString();
  if (workspaceId) url.searchParams.set("workspace_id", workspaceId);
  else url.searchParams.delete("workspace_id");
  return url.toString();
}

// Drops a stored or addressed Workspace that is not (or no longer) one of the person's active Workspaces, e.g. an
// archived one: no choice is left behind, so the default applies again. No event: every view already ignores an
// unknown id (resolveActiveWorkspaceId), so what they show does not change.
export function forgetWorkspacePreference() {
  const key = storageKey();
  if (key) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      // Nothing stored that could be read back.
    }
  }
  const next = hrefWithWorkspace(window.location.href, "");
  if (next !== window.location.href) window.history.replaceState(window.history.state, "", next);
}

export function storeWorkspacePreference(workspaceId: string) {
  const key = storageKey();
  if (key) {
    try {
      window.localStorage.setItem(key, workspaceId || NO_WORKSPACE);
    } catch {
      // The in-memory event below still keeps open views consistent.
    }
  }
  const next = hrefWithWorkspace(window.location.href, workspaceId);
  if (next !== window.location.href) window.history.replaceState(window.history.state, "", next);
  window.dispatchEvent(new CustomEvent(ACTIVE_WORKSPACE_EVENT, { detail: workspaceId }));
}
