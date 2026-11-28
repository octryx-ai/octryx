import { createContext, useContext } from "react";
import type { AdminTab } from "./types/adminPanelTypes.governance";

export type AdminNavigation = { openAdminTab: (tab: AdminTab) => void };

export const AdminNavigationContext = createContext<AdminNavigation>({ openAdminTab: () => {} });

export function useAdminNavigation(): AdminNavigation {
  return useContext(AdminNavigationContext);
}
