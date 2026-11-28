import { ADMIN_TAB_GROUPS } from "./adminPanelTabs";
import type { AdminTabDef, AdminTabGroup } from "./adminPanelTabs";
import {
  ADMIN_AREA_CONFIGS,
  isAdminTabRefVisible,
  type AdminAreaKey,
  type AdminPlatformFeatures,
} from "./adminPanelAreas";
import type { AdminTab } from "../types/adminPanelTypes.governance";

const ADMIN_TAB_BY_ID = new Map<AdminTab, AdminTabDef>(
  ADMIN_TAB_GROUPS.flatMap((group) =>
    group.tabs.flatMap((entry) => [entry, ...(entry.children ?? [])]),
  ).map((entry) => [entry.id, entry]),
);

// Joins the pure area navigation with the tab icons. Admin-only entries are
// hidden for other users and entries of a switched-off platform feature are
// hidden for everyone; this is presentation, not authorization.
export function getAdminAreaTabGroups(
  area: AdminAreaKey,
  isAdmin = true,
  features: AdminPlatformFeatures = {},
  // Platform admin, or admin/owner of the active Workspace (entries marked workspaceAdmin).
  canAdminWorkspace = isAdmin,
  // Platform admin, or admin/owner of any Workspace (entries marked anyWorkspaceAdmin).
  canAdminAnyWorkspace = canAdminWorkspace,
): AdminTabGroup[] {
  return ADMIN_AREA_CONFIGS[area].groups
    .map((group) => ({
      label: group.label,
      tabs: group.tabs
        .filter((tabRef) => isAdminTabRefVisible(tabRef, isAdmin, features, canAdminWorkspace, canAdminAnyWorkspace))
        .flatMap((tabRef): AdminTabDef[] => {
          const tab = ADMIN_TAB_BY_ID.get(tabRef.id);
          return tab ? [{ ...tab, label: tabRef.label ?? tab.label, children: undefined }] : [];
        }),
    }))
    .filter((group) => group.tabs.length > 0);
}
