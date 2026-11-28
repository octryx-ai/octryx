import { resolveProjectSettingsTab, type ProjectSettingsTab } from "./projectSettingsSections";

export type WorkspaceSettingsFocus = "classification";

type Pending = { workspaceId: string; section: ProjectSettingsTab; focus: WorkspaceSettingsFocus | null };

let pending: Pending | null = null;

export function requestWorkspaceSettings(workspaceId: string, section: ProjectSettingsTab, focus: WorkspaceSettingsFocus | null = null): void {
  pending = { workspaceId, section, focus };
}

export function pendingWorkspaceSettings(): string | null {
  return pending?.workspaceId ?? null;
}

export function takeWorkspaceSettingsRequest(workspaceId: string): { section: ProjectSettingsTab; focus: WorkspaceSettingsFocus | null } | null {
  if (!pending || pending.workspaceId !== workspaceId) return null;
  const { section, focus } = pending;
  pending = null;
  return { section, focus };
}

export function takeWorkspaceSettingsSection(workspaceId: string): ProjectSettingsTab | null {
  return takeWorkspaceSettingsRequest(workspaceId)?.section ?? null;
}

const SECTION_PARAM = "section";

export function workspaceSectionHref(workspaceId: string, section: ProjectSettingsTab | "classification" | "documentation"): string {
  return `/chat?${new URLSearchParams({ area: "admin", tab: "projects", workspace_id: workspaceId, [SECTION_PARAM]: section }).toString()}`;
}

export function readUrlWorkspaceSection(search: string): Pending | null {
  const params = new URLSearchParams(search);
  const workspaceId = params.get("workspace_id") || "";
  const value = params.get(SECTION_PARAM);
  if (!workspaceId || value === null) return null;
  if (value === "classification") return { workspaceId, section: "rules", focus: "classification" };
  return { workspaceId, section: resolveProjectSettingsTab(value) ?? "overview", focus: null };
}

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
