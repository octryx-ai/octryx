// Area switches of the app: a switch keeps only what the target area needs; settings open on their admin area.

import type { AdminTab } from "../admin/types/adminPanelTypes.governance";
import { resolveAdminAreaForTab } from "../admin/config/adminPanelAreas";
import { areaSwitchHref } from "./areaNavigation";
import type { WorkspaceArea } from "./workspaceAreas";

export function appAreaNavigation({
  setActiveArea,
  setAdminPanelInitialTab,
  setProfileDropdownOpen,
  setSidebarOpen,
}: {
  setActiveArea: (area: WorkspaceArea) => void;
  setAdminPanelInitialTab: (tab: AdminTab) => void;
  setProfileDropdownOpen: (open: boolean) => void;
  setSidebarOpen: (open: boolean) => void;
}) {
  // An area switch keeps only what the target needs; the page writes its own fields.
  const setWorkspaceArea = (area: WorkspaceArea, params?: Record<string, string>) => {
    setActiveArea(area);
    window.history.pushState(null, "", areaSwitchHref(window.location.href, area, params));
  };
  const openSettingsTab = (
    tab: AdminTab,
    area?: Exclude<WorkspaceArea, "chat" | "work">,
  ) => {
    setAdminPanelInitialTab(tab);
    setWorkspaceArea(area ?? resolveAdminAreaForTab(tab));
    setProfileDropdownOpen(false);
    setSidebarOpen(false);
  };
  return { setWorkspaceArea, openSettingsTab };
}
