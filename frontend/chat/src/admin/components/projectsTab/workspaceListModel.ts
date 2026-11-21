import type { AdminProjectQuality } from "../../types/projectQualityTypes";

// Workspaces list (Settings → Organization → Workspaces): name search plus an
// Active / Inactive / All filter that starts on Active so archived test
// workspaces do not dominate the page.
export type WorkspaceStatusFilter = "active" | "inactive" | "all";

export const DEFAULT_WORKSPACE_STATUS_FILTER: WorkspaceStatusFilter = "active";

export const WORKSPACE_STATUS_FILTER_OPTIONS: Array<{
  value: WorkspaceStatusFilter;
  label: string;
}> = [
  { value: "active", label: "Active workspaces" },
  { value: "inactive", label: "Inactive workspaces" },
  { value: "all", label: "All workspaces" },
];

export function asWorkspaceStatusFilter(value: string): WorkspaceStatusFilter {
  return value === "inactive" || value === "all" ? value : "active";
}

type WorkspaceListItem = Pick<
  AdminProjectQuality,
  "id" | "name" | "description" | "is_active"
> & { is_system?: boolean; template_key?: string | null };

export function filterWorkspaces<T extends WorkspaceListItem>(
  workspaces: readonly T[] | null | undefined,
  query: string,
  status: WorkspaceStatusFilter,
): T[] {
  const items = Array.isArray(workspaces) ? workspaces : [];
  const needle = query.trim().toLowerCase();
  return items
    .filter((workspace) => {
      if (status === "active" && !workspace.is_active) return false;
      if (status === "inactive" && workspace.is_active) return false;
      if (!needle) return true;
      return [workspace.name, workspace.description, workspace.id, workspace.template_key]
        .map((value) => String(value || "").toLowerCase())
        .some((value) => value.includes(needle));
    })
    .sort((left, right) => {
      // The protected system workspace stays on top, the rest is alphabetical.
      if (Boolean(left.is_system) !== Boolean(right.is_system)) {
        return left.is_system ? -1 : 1;
      }
      return String(left.name || "").localeCompare(String(right.name || ""));
    });
}

export function countWorkspacesByStatus(
  workspaces: readonly WorkspaceListItem[] | null | undefined,
): Record<WorkspaceStatusFilter, number> {
  const items = Array.isArray(workspaces) ? workspaces : [];
  const active = items.filter((workspace) => workspace.is_active).length;
  return { active, inactive: items.length - active, all: items.length };
}
