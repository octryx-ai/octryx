import type { AdminTab } from "../admin/types/adminPanelTypes.governance";
import type { WorkspaceArea } from "./workspaceAreas";

export type WorkspaceDestination = { area: WorkspaceArea; label: string; adminTab?: AdminTab };

export function getWorkspaceDestinations(isAdmin: boolean, canReadWork: boolean): WorkspaceDestination[] {
  return [
    { area: "chat", label: "Chat" },
    { area: "knowledge", label: "Knowledge", adminTab: "knowledgeLibrary" },
    canReadWork ? { area: "work", label: "Work" } : { area: "coding", label: "Work" },
    { area: "agents", label: "Agents" },
    ...(isAdmin ? [
      { area: "operations", label: "Operations", adminTab: "observabilityOverview" },
      { area: "admin", label: "Admin", adminTab: "users" },
    ] as WorkspaceDestination[] : []),
  ];
}

export function codingWorkspaceView(canManageWork: boolean): "work" | "repositories" {
  return canManageWork ? "work" : "repositories";
}

export function isDestinationActive(destination: WorkspaceDestination, activeArea: WorkspaceArea): boolean {
  if (destination.area === activeArea) return true;
  if (destination.label === "Work") return activeArea === "work" || activeArea === "coding";
  return destination.area === "agents" && activeArea === "workflows";
}

/** A member asking for an admin area (a link) gets the area the rail offers instead of a refusal. */
export function areaForRole(area: WorkspaceArea, isAdmin: boolean): WorkspaceArea {
  if (isAdmin) return area;
  if (area === "workflows") return "agents";
  if (area === "operations") return "chat";
  return area;
}
