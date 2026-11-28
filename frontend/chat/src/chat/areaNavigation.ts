import type { WorkspaceArea } from "./workspaceAreas";

const TAB_PARAM = "tab";

const AREAS: ReadonlySet<string> = new Set<WorkspaceArea>([
  "chat", "knowledge", "work", "coding", "agents", "workflows", "admin", "operations", "personal", "help",
]);

export function workspaceAreaFromKey(area: string | null | undefined): WorkspaceArea | null {
  return area && AREAS.has(area) ? (area as WorkspaceArea) : null;
}

const KEEP_ALWAYS = ["workspace_id"];
const KEEP_FOR: Partial<Record<WorkspaceArea, string[]>> = {
  chat: ["session_id"],
  work: ["work_item_id"],
  coding: ["work_item_id"],
  operations: ["decision", "policy"],
  workflows: ["session"],
};

export function areaSwitchHref(href: string, area: WorkspaceArea, params: Record<string, string> = {}): string {
  const current = new URL(href);
  const next = new URL(current.pathname, current.origin);
  if (area !== "chat") next.searchParams.set("area", area);
  for (const key of [...KEEP_ALWAYS, ...(KEEP_FOR[area] ?? [])]) {
    const value = current.searchParams.get(key);
    if (value) next.searchParams.set(key, value);
  }
  for (const [key, value] of Object.entries(params)) next.searchParams.set(key, value);
  return next.toString();
}
// replaceState fires no event of its own, so readers of the address listen for this.
export const AREA_TAB_EVENT = "octryx:area-tab";

export function readAreaTabFromSearch(search: string): string | null {
  try {
    return new URLSearchParams(search).get(TAB_PARAM);
  } catch {
    return null;
  }
}

export function withAreaTab(href: string, tab: string | null): string {
  const url = new URL(href);
  if (tab) url.searchParams.set(TAB_PARAM, tab);
  else url.searchParams.delete(TAB_PARAM);
  return url.toString();
}

export function writeAreaTabToUrl(tab: string | null) {
  if (typeof window === "undefined") return;
  const next = withAreaTab(window.location.href, tab);
  if (next === window.location.href) return;
  window.history.replaceState(window.history.state, "", next);
  window.dispatchEvent(new Event(AREA_TAB_EVENT));
}
