import type { AdminTab } from "../admin/types/adminPanelTypes.governance";
import type { WorkspaceArea } from "./workspaceAreas";

export type WorkspaceDestination = { area: WorkspaceArea; label: string; adminTab?: AdminTab };

// Every Workspace member reads Work (a team leader shows the team its work); who has no Workspace
// and no Work role explores repositories only. Changing work keeps its own gate (work/workAccess.ts).
export function getWorkspaceDestinations(isAdmin: boolean, canReadWork: boolean): WorkspaceDestination[] {
  return [
    { area: "chat", label: "Chat" },
    { area: "knowledge", label: "Knowledge", adminTab: "knowledgeLibrary" },
    // Work and Coding are one area with one menu. People without work access open its Repositories.
    canReadWork ? { area: "work", label: "Work" } : { area: "coding", label: "Work" },
    // Every Workspace member sees the Workspace's agent clients (admin-only columns are the server's call).
    { area: "agents", label: "Agents" },
    // Operations and Admin are admin pages: members do not run the platform (what the rail shows opens).
    ...(isAdmin ? [
      { area: "operations", label: "Operations", adminTab: "observabilityOverview" },
      // Settings, Runtime and Automation in one Admin area, for admins only (its pages are admin-gated).
      { area: "admin", label: "Admin", adminTab: "users" },
    ] as WorkspaceDestination[] : []),
  ];
}

// Who manages work gets the Work pages, Repositories among them (`coding_view=repositories` opens it there);
// a member gets the repository list alone, whatever page the address asks for.
export function codingWorkspaceView(canManageWork: boolean): "work" | "repositories" {
  return canManageWork ? "work" : "repositories";
}

/** Whether a rail entry is the current area; Work also stands for the Coding pages, Agents for the builder pages. */
export function isDestinationActive(destination: WorkspaceDestination, activeArea: WorkspaceArea): boolean {
  if (destination.area === activeArea) return true;
  if (destination.label === "Work") return activeArea === "work" || activeArea === "coding";
  // The builder pages (`workflows`) are part of the one Agents area.
  return destination.area === "agents" && activeArea === "workflows";
}

/** The area a person sees for the address's area: a member asked for an admin area (a link) gets the area its
 * rail offers instead of a refusal (what the navigation offers opens). The builder pages
 * (`workflows`) fall back to the Agents pages, Operations to the chat. */
export function areaForRole(area: WorkspaceArea, isAdmin: boolean): WorkspaceArea {
  if (isAdmin) return area;
  if (area === "workflows") return "agents";
  if (area === "operations") return "chat";
  return area;
}
