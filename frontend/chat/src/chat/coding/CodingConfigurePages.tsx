// The Coding page's configure pages: repositories, delivery pipeline and coding rules.

import { lazy, Suspense } from "react";
import { ProposedChecks } from "./governance/ProposedChecks";
import { CodingDeliveryPipeline } from "./governance/CodingDeliveryPipeline";
import { CodingEffectiveRules } from "./governance/CodingEffectiveRules";
import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import type { CodingNavKey } from "./CodingAreaNav";
import { LoadingState } from "../../layout/LoadingState";

// Work › Repositories: the repository list is the body of this page, loaded when it is opened.
const RepositoryList = lazy(async () => ({ default: (await import("./repository/RepositoryList")).RepositoryList }));

export function CodingConfigurePages({ activeQueue, workspaceId, workspaceName, activeNav, activeNavItem,
  onOpenAdminTab, openWorkspaceSettings, setActiveNav, addingRule, setAddingRule, setRulesEditable }: {
  activeQueue: string | null;
  workspaceId: string;
  workspaceName: string;
  activeNav: CodingNavKey;
  activeNavItem: { label: string };
  onOpenAdminTab?: (tab: AdminTab) => void;
  openWorkspaceSettings: (section: "connectors" | "repositories" | "access" | "coding") => void;
  setActiveNav: (key: CodingNavKey) => void;
  addingRule: boolean;
  setAddingRule: (adding: boolean) => void;
  setRulesEditable: (editable: boolean) => void;
}) {
  return (
    <>
      {!activeQueue && !workspaceId ? (
        <div className="admin-panel__empty-state">Select a workspace to see its {activeNavItem.label.toLowerCase()}.</div>
      ) : null}
      {workspaceId && activeNav === "repositories" ? (
        <Suspense fallback={<LoadingState label="repositories" />}>
          <RepositoryList key={workspaceId} workspaceId={workspaceId} workspaceControl={null} embedded
            onOpenRepositorySettings={() => openWorkspaceSettings("repositories")} />
        </Suspense>
      ) : null}
      {workspaceId && activeNav === "pipelines" ? <CodingDeliveryPipeline workspaceId={workspaceId} /> : null}
      {workspaceId && activeNav === "rules" ? <ProposedChecks key={`proposed-${workspaceId}`} workspaceId={workspaceId} /> : null}
      {workspaceId && activeNav === "rules" ? (
        <CodingEffectiveRules key={workspaceId} workspaceId={workspaceId} workspaceName={workspaceName}
          onOpenAdminTab={(tab) => onOpenAdminTab?.(tab)} onOpenPipeline={() => setActiveNav("pipelines")}
          onOpenWorkspaceCoding={() => openWorkspaceSettings("coding")}
          adding={addingRule} onAddingChange={setAddingRule} onEditableChange={setRulesEditable} />
      ) : null}
    </>
  );
}
