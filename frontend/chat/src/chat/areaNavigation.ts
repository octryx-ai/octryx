// URL contract of the workspace areas: `?area=<area>&tab=<page>`. A reload or a
// shared link opens the same page; the area resolver discards a tab that does
// not belong to the area.
import type { WorkspaceArea } from "./workspaceAreas";

const TAB_PARAM = "tab";

const AREAS: ReadonlySet<string> = new Set<WorkspaceArea>([
  "chat", "knowledge", "work", "coding", "agents", "workflows", "admin", "operations", "personal", "help",
]);

/** The area an `area` key names; null for anything that is not a current area key. */
export function workspaceAreaFromKey(area: string | null | undefined): WorkspaceArea | null {
  return area && AREAS.has(area) ? (area as WorkspaceArea) : null;
}

// What an area switch keeps of the current address: the Workspace, and the item focus that
// Work and Coding hand to each other. Everything else belongs to the page that is being left.
const KEEP_ALWAYS = ["workspace_id"];
// Pages that are opened with a hand-off in the address keep it: Operations → Decisions filtered to a decision or
// a policy (Admin → Policies "Show decisions"), the Effective setup of a chat turn, a workflow to open.
const KEEP_FOR: Partial<Record<WorkspaceArea, string[]>> = {
  chat: ["session_id"],
  work: ["work_item_id"],
  coding: ["work_item_id"],
  operations: ["decision", "policy"],
  workflows: ["session", "flow_id", "new_flow"],
};

/**
 * The address for switching to an area: only the area, what that area needs from the current address, and the
 * page fields the caller names (e.g. `coding_view` when a Work menu entry opens a Coding page).
 */
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
// Fired after the page of an area changed in the address (a replaceState fires no event of its own), so what reads
// the page from the address, such as the help panel, follows it.
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
