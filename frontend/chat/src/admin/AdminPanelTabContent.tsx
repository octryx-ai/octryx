// The admin panel content with the derived tab contexts of the container.
import { AdminPanelContent } from "./components/AdminPanelContent";
import type { useAdminPanelDerived } from "./hooks/useAdminPanelContainerCore";
import { readJson } from "./utils/adminPanelHelpers";
import type { AdminTab } from "./types/adminPanelTypes.governance";
import type { ProjectOption } from "../chatOptionTypes";

type AdminPanelTabContentProps = {
  derived: ReturnType<typeof useAdminPanelDerived>;
  loadingTab: boolean;
  tabError: string | null;
  onRetry: () => void;
  tab: AdminTab;
  projects: ProjectOption[];
  brandingEnabled: boolean;
  isAdmin: boolean;
  currentUserId?: string;
};

export function AdminPanelTabContent(props: AdminPanelTabContentProps) {
  const { derived, loadingTab, tabError, onRetry, tab, projects, brandingEnabled, isAdmin, currentUserId } = props;
  const {
    agentsTabCtx,
    brandingTabCtx,
    channelsTabCtx,
    knowledgeTabCtx,
    mcpTabCtx,
    projectsTabCtx,
    providersTabCtx,
    runtimesTabCtx,
    schedulersTabCtx,
    skillsTabCtx,
    tasksTabCtx,
    toolCatalogTabCtx,
    ttsTabCtx,
    usersTabCtx,
    webhooksTabCtx,
    connectorsTabCtx,
  } = derived;
  return (
    <AdminPanelContent
      loadingTab={loadingTab}
      tabError={tabError}
      onRetry={onRetry}
      tab={tab}
      projects={projects}
      readJson={readJson}
      usersTabCtx={usersTabCtx}
      projectsTabCtx={projectsTabCtx}
      providersTabCtx={providersTabCtx}
      runtimesTabCtx={runtimesTabCtx}
      connectorsTabCtx={connectorsTabCtx}
      toolCatalogTabCtx={toolCatalogTabCtx}
      knowledgeTabCtx={knowledgeTabCtx}
      agentsTabCtx={agentsTabCtx}
      schedulersTabCtx={schedulersTabCtx}
      tasksTabCtx={tasksTabCtx}
      webhooksTabCtx={webhooksTabCtx}
      channelsTabCtx={channelsTabCtx}
      mcpTabCtx={mcpTabCtx}
      ttsTabCtx={ttsTabCtx}
      skillsTabCtx={skillsTabCtx}
      brandingTabCtx={brandingTabCtx}
      brandingEnabled={brandingEnabled}
      isAdmin={isAdmin}
      currentUserId={currentUserId}
    />
  );
}
