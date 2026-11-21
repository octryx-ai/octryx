import { resolveProjectSettingsTab, type ProjectSettingsTab } from "./projectSettingsSections";

// A one-shot request to open one Workspace's settings drawer on a section (Work and Coding link to
// Workspace → Connectors, Repositories or Access, the one place those are declared). The Workspaces page
// takes the request when it shows that Workspace; the drawer takes the section when it opens.

// A part of the section to show first ("Set class" in the Workspaces list opens the classification card).
export type WorkspaceSettingsFocus = "classification";

type Pending = { workspaceId: string; section: ProjectSettingsTab; focus: WorkspaceSettingsFocus | null };

let pending: Pending | null = null;

export function requestWorkspaceSettings(workspaceId: string, section: ProjectSettingsTab, focus: WorkspaceSettingsFocus | null = null): void {
  pending = { workspaceId, section, focus };
}

/** The Workspace a pending request names (it stays pending until the drawer takes the section). */
export function pendingWorkspaceSettings(): string | null {
  return pending?.workspaceId ?? null;
}

/** The requested section (and the part to show first) for ``workspaceId``, once; null when nothing was requested. */
export function takeWorkspaceSettingsRequest(workspaceId: string): { section: ProjectSettingsTab; focus: WorkspaceSettingsFocus | null } | null {
  if (!pending || pending.workspaceId !== workspaceId) return null;
  const { section, focus } = pending;
  pending = null;
  return { section, focus };
}

/** The requested section for ``workspaceId``, once; null when nothing was requested for it. */
export function takeWorkspaceSettingsSection(workspaceId: string): ProjectSettingsTab | null {
  return takeWorkspaceSettingsRequest(workspaceId)?.section ?? null;
}

// Deep link to one Workspace's settings section (seat-card finding):
// `/chat?area=admin&tab=projects&workspace_id=<id>&section=<key>`. `section` is a settings section key (overview,
// models, coding, rules, …), `classification` (Rules with the seat card on top) or an alias such as `documentation`
// (Knowledge with the Documentation target card); unknown values open the overview.
const SECTION_PARAM = "section";

/** The address of one Workspace's settings section in Admin › Workspaces. */
export function workspaceSectionHref(workspaceId: string, section: ProjectSettingsTab | "classification" | "documentation"): string {
  return `/chat?${new URLSearchParams({ area: "admin", tab: "projects", workspace_id: workspaceId, [SECTION_PARAM]: section }).toString()}`;
}

/** The request a deep link names (null without `workspace_id` + `section`). */
export function readUrlWorkspaceSection(search: string): Pending | null {
  const params = new URLSearchParams(search);
  const workspaceId = params.get("workspace_id") || "";
  const value = params.get(SECTION_PARAM);
  if (!workspaceId || value === null) return null;
  if (value === "classification") return { workspaceId, section: "rules", focus: "classification" };
  return { workspaceId, section: resolveProjectSettingsTab(value) ?? "overview", focus: null };
}

/** Turns a deep link in the address into a pending request, once (the parameter is removed from the address). */
export function takeUrlWorkspaceSection(): void {
  if (typeof window === "undefined") return;
  const request = readUrlWorkspaceSection(window.location.search);
  if (!request) return;
  requestWorkspaceSettings(request.workspaceId, request.section, request.focus);
  const params = new URLSearchParams(window.location.search);
  params.delete(SECTION_PARAM);
  const query = params.toString();
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
}
