import type { WorkItem } from "../workItemTypes";

// "My work": the person says once per Workspace who they are in Jira, and My work
// shows the items assigned to that Jira account. Never matched by e-mail or name: without the person's explicit
// choice there is no My work, only the choice. Pure: no React.
//
// Server contract (proposed to the backend session, not on the server yet):
//   GET    /api/v1/workspaces/{id}/work/me -> { source_type: "jira", account_id: string | null, display_name: string | null }
//   PUT    /api/v1/workspaces/{id}/work/me    { source_type: "jira", account_id }  -> the same shape
//   DELETE /api/v1/workspaces/{id}/work/me                                          -> { account_id: null, ... }
// A 404 means this server cannot store the choice yet (needs configuration).

export type JiraIdentity = { accountId: string; displayName: string };

export type MyWorkState =
  | { kind: "loading" }
  | { kind: "unavailable" }
  | { kind: "error"; message: string }
  | { kind: "unset" }
  | { kind: "set"; identity: JiraIdentity };

export type WorkItemsScope = "mine" | "all";

export function myWorkPath(workspaceId: string): string {
  return `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/work/me`;
}

/** The stored choice, or null when the person has not chosen yet. */
export function readJiraIdentity(payload: unknown): JiraIdentity | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  const accountId = typeof record.account_id === "string" ? record.account_id.trim() : "";
  if (!accountId) return null;
  const displayName = typeof record.display_name === "string" ? record.display_name.trim() : "";
  return { accountId, displayName: displayName || accountId };
}

/** The state after a load: 404 → the server cannot keep the choice; any other refusal → an error to retry. */
export function myWorkStateFrom(status: number, payload: unknown): MyWorkState {
  if (status === 404) return { kind: "unavailable" };
  if (status < 200 || status >= 300) {
    const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : null;
    const code = detail && typeof detail === "object" ? (detail as { code?: unknown }).code : null;
    if (code === "unknown_jira_account") {
      return { kind: "error", message: "This person has no Jira items in this Workspace. Choose someone from the list." };
    }
    const message = typeof detail === "string" ? detail
      : detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string"
        ? String((detail as { message: string }).message) : "";
    return { kind: "error", message: message || "Who you are in Jira could not be loaded." };
  }
  const identity = readJiraIdentity(payload);
  return identity ? { kind: "set", identity } : { kind: "unset" };
}

/** The scope as stored in the browser (the person's last choice), or null when nothing valid is stored. */
export function readStoredScope(value: string | null | undefined): WorkItemsScope | null {
  return value === "mine" || value === "all" ? value : null;
}

/** Where the person's last choice is kept: per Workspace, in this browser. */
export function scopeStorageKey(workspaceId: string): string {
  return `octryx.work.scope.${workspaceId}`;
}

/**
 * The scope the page opens with: My work, unless the person last chose All items in this Workspace.
 * Without a choice of who they are in Jira, My work offers that choice, the next step. Only when this server cannot
 * keep the choice, or reading it failed, the page opens on every item.
 */
export function defaultScope(state: MyWorkState, stored: WorkItemsScope | null = null): WorkItemsScope {
  if (state.kind === "unavailable" || state.kind === "error") return "all";
  return stored ?? "mine";
}

/** The items the scope shows: My work keeps only the chosen Jira account's items (by id, never by name). */
export function itemsInScope(items: WorkItem[], scope: WorkItemsScope, state: MyWorkState): WorkItem[] {
  if (scope !== "mine") return items;
  if (state.kind !== "set") return [];
  return items.filter((item) => (item.assignee || "").trim() === state.identity.accountId);
}

/** Whether My work shows its panel (the choice, or why it is not possible) instead of items. */
export function needsChoice(scope: WorkItemsScope, state: MyWorkState, changing = false): boolean {
  return scope === "mine" && (state.kind !== "set" || changing);
}

/** One sentence for the My work panel when it cannot show items. */
export function myWorkMessage(state: MyWorkState): string {
  if (state.kind === "loading") return "Loading who you are in Jira…";
  if (state.kind === "unavailable") {
    return "My work needs configuration: this server cannot store who you are in Jira yet. All items stay available.";
  }
  if (state.kind === "error") return state.message;
  if (state.kind === "unset") return "Choose who you are in Jira. My work then shows the items assigned to you.";
  return "";
}
