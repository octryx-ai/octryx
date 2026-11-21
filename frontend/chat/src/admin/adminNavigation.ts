import { createContext, useContext } from "react";
import type { AdminTab } from "./types/adminPanelTypes.governance";

// Lets any admin page link to a page in another area (for example a project's
// Connectors section to Automation → Connectors) instead of describing where
// to go. The provider lives in AdminPanelContainer.
export type AdminNavigation = { openAdminTab: (tab: AdminTab) => void };

export const AdminNavigationContext = createContext<AdminNavigation>({ openAdminTab: () => {} });

export function useAdminNavigation(): AdminNavigation {
  return useContext(AdminNavigationContext);
}
