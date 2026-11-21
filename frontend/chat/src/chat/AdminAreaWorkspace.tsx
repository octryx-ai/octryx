import { Suspense, lazy } from "react";

import { ChatErrorBoundary } from "./ChatErrorBoundary";
import type { AdminAreaKey } from "../admin/config/adminPanelAreas";
import type { AdminTab } from "../admin/types/adminPanelTypes.governance";
import type { ChatState } from "../types";
import type { ProjectOption } from "../chatOptionTypes";
import { LoadingState } from "../layout/LoadingState";
import { AGENTS_AREA_ENTRIES } from "./agents/agentsAreaMenu";
import { AgentsNavIcon } from "./agents/AgentsAreaNav";
import type { AdminExternalNavEntry } from "../admin/components/AdminExternalNav";
import { RETURN_TO_CONNECTIONS } from "./navigation/adminReturn";

// A link: the icon of the Connections entries that open a page of another area.
const LINK_ICON = (
  <svg viewBox="0 0 20 20" aria-hidden="true">
    <path d="M8.5 11.5l3-3" /><path d="M7 9l-2 2a2.5 2.5 0 0 0 3.5 3.5l2-2" /><path d="M13 11l2-2a2.5 2.5 0 0 0-3.5-3.5l-2 2" />
  </svg>
);

type OpenArea = (area: "agents" | "help" | "work" | "coding", params?: Record<string, string>) => void;

// Repositories and Jira write-back left the Work menu for Admin › Connections (until the connection page holds
// them as sections); they still open in their own component, with a link back to Admin › Connections above them.
function connectionPagesAsExternalNav(onOpenArea?: OpenArea): AdminExternalNavEntry[] {
  return [
    { group: "Connections", key: "coding:repositories", label: "Repositories", icon: LINK_ICON, position: "end",
      onSelect: () => onOpenArea?.("coding", { coding_view: "repositories", ...RETURN_TO_CONNECTIONS }) },
    { group: "Connections", key: "work:writeback", label: "Jira write-back", icon: LINK_ICON, position: "end",
      onSelect: () => onOpenArea?.("work", { work_view: "writeback", ...RETURN_TO_CONNECTIONS }) },
  ];
}

// The Agents pages of the one Agents menu (agents/agentsAreaMenu.ts), listed in the builder's sidebar.
function agentsPagesAsExternalNav(onOpenArea?: OpenArea): AdminExternalNavEntry[] {
  return AGENTS_AREA_ENTRIES.flatMap((entry) => entry.host === "agents" ? [{
    group: entry.group, key: `agents:${entry.key}`, label: entry.label, icon: <AgentsNavIcon navKey={entry.key} />,
    onSelect: () => onOpenArea?.("agents", { agents_view: entry.key }),
  }] : []);
}

const AdminPanel = lazy(async () => {
  const module = await import("../admin/AdminPanelContainer");
  return { default: module.AdminPanelContainer };
});

type AdminAreaWorkspaceProps = {
  area: AdminAreaKey;
  activeBranding: ChatState["branding"];
  adminPanelInitialTab: AdminTab;
  chatState: ChatState | null;
  currentUserId?: string;
  isAdmin?: boolean;
  onOpenAdminTab?: (tab: AdminTab) => void;
  loadState: (
    search: string,
    options?: { silent?: boolean; preserveTrace?: boolean },
  ) => Promise<void>;
  onApprovalStateChanged?: (sessionId?: string | null) => void;
  projects: ProjectOption[];
  // Opens a page of another component of the same area (the Agents pages beside the builder).
  onOpenArea?: OpenArea;
};

export function AdminAreaWorkspace({
  area,
  activeBranding,
  adminPanelInitialTab,
  chatState,
  currentUserId,
  isAdmin = true,
  onOpenAdminTab,
  loadState,
  onApprovalStateChanged,
  projects,
  onOpenArea,
}: AdminAreaWorkspaceProps) {
  // The setup guide is reached from the rail ("Setup n/7"), not from Admin's menu; Repositories
  // and Jira write-back are views of Admin › Connections.
  const externalNav = area === "workflows"
    ? agentsPagesAsExternalNav(onOpenArea)
    : area === "admin"
      ? connectionPagesAsExternalNav(onOpenArea)
      : undefined;
  return (
    <main className="admin-area-workspace">
      <Suspense fallback={<div className="admin-area-workspace__loading"><LoadingState label="this area" variant="page" /></div>}>
        <ChatErrorBoundary fallbackTitle="This page could not be displayed">
          <AdminPanel
            area={area}
            branding={activeBranding}
            initialTab={adminPanelInitialTab}
            projects={projects}
            currentUserId={currentUserId}
            isAdmin={isAdmin}
            onOpenAdminTab={onOpenAdminTab}
            externalNav={externalNav}
            onApprovalStateChanged={(sessionId?: string | null) => {
              onApprovalStateChanged?.(sessionId);
              if (!sessionId || sessionId !== chatState?.selectedSession?.id) {
                return;
              }
              void loadState(window.location.search, {
                silent: true,
                preserveTrace: true,
              });
            }}
          />
        </ChatErrorBoundary>
      </Suspense>
    </main>
  );
}
