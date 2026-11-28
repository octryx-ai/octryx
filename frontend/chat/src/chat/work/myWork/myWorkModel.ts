import type { WorkItem } from "../workItemTypes";

// Never matched by e-mail or name: only the person's explicit choice counts.

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

export function readJiraIdentity(payload: unknown): JiraIdentity | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as Record<string, unknown>;
  const accountId = typeof record.account_id === "string" ? record.account_id.trim() : "";
  if (!accountId) return null;
  const displayName = typeof record.display_name === "string" ? record.display_name.trim() : "";
  return { accountId, displayName: displayName || accountId };
}

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

export function readStoredScope(value: string | null | undefined): WorkItemsScope | null {
  return value === "mine" || value === "all" ? value : null;
}

export function scopeStorageKey(workspaceId: string): string {
  return `octryx.work.scope.${workspaceId}`;
}

export function defaultScope(state: MyWorkState, stored: WorkItemsScope | null = null): WorkItemsScope {
  if (state.kind === "unavailable" || state.kind === "error") return "all";
  return stored ?? "mine";
}

export function itemsInScope(items: WorkItem[], scope: WorkItemsScope, state: MyWorkState): WorkItem[] {
  if (scope !== "mine") return items;
  if (state.kind !== "set") return [];
  return items.filter((item) => (item.assignee || "").trim() === state.identity.accountId);
}

export function needsChoice(scope: WorkItemsScope, state: MyWorkState, changing = false): boolean {
  return scope === "mine" && (state.kind !== "set" || changing);
}

export function myWorkMessage(state: MyWorkState): string {
  if (state.kind === "loading") return "Loading who you are in Jira…";
  if (state.kind === "unavailable") {
    return "My work needs configuration: this server cannot store who you are in Jira yet. All items stay available.";
  }
  if (state.kind === "error") return state.message;
  if (state.kind === "unset") return "Choose who you are in Jira. My work then shows the items assigned to you.";
  return "";
}
