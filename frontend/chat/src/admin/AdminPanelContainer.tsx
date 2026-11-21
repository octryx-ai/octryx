import { AdminPanelShell } from "./components/AdminPanelShell";
import type { AdminExternalNavEntry } from "./components/AdminExternalNav";
import {
  useAdminPanelControllers,
  useAdminPanelCore,
  useAdminPanelDerived,
} from "./hooks/useAdminPanelContainerCore";
import { AdminPanelTabContent } from "./AdminPanelTabContent";
import {
  resolveAdminAreaForTab,
  resolveAdminAreaTabLabel,
  WORKSPACE_ADMIN_ENTRY_AREAS,
  type AdminAreaKey,
} from "./config/adminPanelAreas";
import { AdminNavigationContext } from "./adminNavigation";
import { resolveAdminEntryTab } from "./config/adminEntries";
import { useWorkspaceAdmin } from "./components/operations/useWorkspaceAdmin";
import type { AdminTab } from "./types/adminPanelTypes.governance";
import type { ChatState } from "../types";
import type { ProjectOption } from "../chatOptionTypes";

export type AdminPanelProps = {
  area?: AdminAreaKey;
  onClose?: () => void;
  branding?: ChatState["branding"];
  initialTab?: AdminTab;
  projects: ProjectOption[];
  currentUserId?: string;
  isAdmin?: boolean;
  // Opens a page that lives in another area; same-area pages switch locally.
  onOpenAdminTab?: (tab: AdminTab) => void;
  onApprovalStateChanged?: (sessionId?: string | null) => void;
  externalNav?: AdminExternalNavEntry[];
};

export function AdminPanelContainer({
  area = "admin",
  onClose,
  branding,
  initialTab = "adminProblems",
  projects,
  currentUserId,
  isAdmin = true,
  onOpenAdminTab,
  onApprovalStateChanged,
  externalNav,
}: AdminPanelProps) {
  const core = useAdminPanelCore(area, initialTab, isAdmin);
  const { tab, setTab } = core;
  const closePanel = onClose ?? (() => {});
  const brandingEnabled = branding?.enabled === true;
  const controllers = useAdminPanelControllers(core, onApprovalStateChanged);
  const derived = useAdminPanelDerived(core, controllers, { onClose: closePanel, projects, currentUserId });
  const areaTabLabel = resolveAdminAreaTabLabel(area, tab) ?? derived.currentTabLabel;

  // Workspace-admin entries (Operations › Costs, Knowledge › Sources): platform admins, and admins/owners of the
  // active Workspace.
  const canAdminWorkspace = useWorkspaceAdmin(isAdmin, projects, WORKSPACE_ADMIN_ENTRY_AREAS.has(area));
  const openAdminTab = (requested: AdminTab) => {
    const target = resolveAdminEntryTab(requested);
    if (resolveAdminAreaForTab(target) === area || !onOpenAdminTab) setTab(target);
    else onOpenAdminTab(target);
  };

  return (
    <AdminNavigationContext.Provider value={{ openAdminTab }}>
    <AdminPanelShell
      area={area}
      onClose={onClose}
      tab={tab}
      setTab={setTab}
      currentTabLabel={areaTabLabel}
      isAdmin={isAdmin}
      features={{ branding: brandingEnabled }}
      canAdminWorkspace={canAdminWorkspace}
      externalNav={externalNav}
    >
      <AdminPanelTabContent
        derived={derived}
        loadingTab={core.loadingTab}
        tabError={core.tabError}
        onRetry={() => void controllers.loadTab(tab)}
        tab={tab}
        projects={projects}
        brandingEnabled={brandingEnabled}
        isAdmin={isAdmin}
        currentUserId={currentUserId}
      />
    </AdminPanelShell>
    </AdminNavigationContext.Provider>
  );
}
