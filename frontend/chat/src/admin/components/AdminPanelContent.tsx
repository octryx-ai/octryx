import { Suspense, type ReactNode } from "react";
import { AdminPanelLoadBoundary } from "./AdminPanelLoadBoundary";
import { LoadingState } from "../../layout/LoadingState";
import type { AdminPanelContentProps } from "./adminPanelContentTypes";
import {
  ObservabilityRunsPage, ObservabilityOverviewPage, ComplianceAuditPage,
  ObservabilityHealthPage, ObservabilityAuditPage, ApprovalDetailPage, ObservabilityDecisionsPage,
  OperationsCostsPage, OperationsLivePage, AdminProblemsPage, RestApisPage, RestApiCallsPage, ConnectionsPage,
  WorkRolesPage, WorkFunctionsPage, WorkRolesAuditPage, PlatformPage, PluginsPage,
  EffectiveSetupPage, WorkflowsPage, InstructionsPage,
  AdminPromptCatalogTab, AdminAgentsTab, AdminWorkspaceKnowledgeTab, KnowledgeAdminPage,
  AdminCorpIdentityTab, AdminBrandingTab, AdminBackupRestoreTab, AdminCallAgentsTab, AdminPersonalityTab,
  AdminChannelsTab, AdminConnectorsTab, AdminDatabasesTab, AdminKnowledgeTab, AdminMcpTab, ToolApprovalsPage,
  AdminResearchPoliciesTab, AdminProjectsTab, AdminModelCatalog, AdminModelsOverview, AdminDefaultAndFallback,
  AdminLimitsAndBudgets, AdminPolicyListsSection, AdminProvidersTab, AdminRuntimesTab, ContentSecurityPage,
  CommandSafetyPage, AdminClassificationPolicy, AdminApprovalRule, AdminCedarPolicies,
  AdminSkillsTab, AdminSchedulersTab, AdminTasksTab, AdminToolCatalogTab, AdminVoiceAndSpeech,
  ObservabilityUsagePage, AdminUsersTab, AdminWebhooksTab, KnowledgeAreaPage,
} from "./adminPanelLazyPages";

type RenderLazyTab = (node: ReactNode) => ReactNode;

// Platform, identity and Workspace pages.
function platformTab(tab: string, props: AdminPanelContentProps, renderLazyTab: RenderLazyTab): ReactNode | undefined {
  const { projects, readJson, usersTabCtx, projectsTabCtx, isAdmin = false } = props;
  switch (tab) {
    case "adminProblems":
      return renderLazyTab(<AdminProblemsPage projects={projects} isAdmin={isAdmin} />);
    case "adminConnections":
      return renderLazyTab(<ConnectionsPage projects={projects} isAdmin={isAdmin} />);
    case "platformVersion": case "platformDevices":
      return renderLazyTab(<PlatformPage page={tab} />);
    case "restApis":
      return renderLazyTab(<RestApisPage projects={projects} />);
    case "restApiCalls":
      return renderLazyTab(<RestApiCallsPage />);
    case "plugins":
      return renderLazyTab(<PluginsPage mode="platform" workspaces={projects} isPlatformAdmin={isAdmin} />);
    case "users":
      return renderLazyTab(<AdminUsersTab ctx={usersTabCtx} section="users" />);
    case "workRoles":
      return renderLazyTab(<WorkRolesPage projects={projects} isAdmin={isAdmin} />);
    case "workRoleFunctions":
      return renderLazyTab(<WorkFunctionsPage isAdmin={isAdmin} />);
    case "workRoleAudit":
      return renderLazyTab(<WorkRolesAuditPage />);
    case "identityRoles":
      return renderLazyTab(<AdminUsersTab ctx={usersTabCtx} section="roles" />);
    case "identityGroups":
      return renderLazyTab(<AdminUsersTab ctx={usersTabCtx} section="groups" />);
    case "identityProviders":
      return renderLazyTab(<AdminUsersTab ctx={usersTabCtx} section="providers" />);
    case "identityAccess":
      return renderLazyTab(<AdminUsersTab ctx={usersTabCtx} section="access" />);
    case "projects":
      return renderLazyTab(<AdminProjectsTab ctx={projectsTabCtx} isAdmin={isAdmin} />);
    case "backupRestore":
      return renderLazyTab(<AdminBackupRestoreTab projects={projects} readJson={readJson} />);
    default:
      return undefined;
  }
}

// Tool policies, research policies, models and runtime execution.
function governanceTab(tab: string, props: AdminPanelContentProps, renderLazyTab: RenderLazyTab): ReactNode | undefined {
  const { projects, providersTabCtx, runtimesTabCtx } = props;
  switch (tab) {
    case "policies":
      return renderLazyTab(<ToolApprovalsPage />);
    case "researchPolicies":
      return renderLazyTab(<AdminResearchPoliciesTab projects={projects} />);
    case "providers":
      return renderLazyTab(<AdminProvidersTab ctx={providersTabCtx} />);
    case "modelCatalog":
      return renderLazyTab(<AdminModelCatalog />);
    case "modelsOverview":
      return renderLazyTab(<AdminModelsOverview />);
    case "modelOrder":
      return renderLazyTab(<AdminDefaultAndFallback />);
    case "runtimePolicyLists":
      return renderLazyTab(<AdminPolicyListsSection />);
    case "runtimeExecution":
      return renderLazyTab(<AdminRuntimesTab ctx={runtimesTabCtx} section="execution" />);
    default:
      return undefined;
  }
}

// Safety, classification, approval and Cedar policies, runtime limits.
function policyTab(tab: string, props: AdminPanelContentProps, renderLazyTab: RenderLazyTab): ReactNode | undefined {
  const { runtimesTabCtx, isAdmin = false } = props;
  switch (tab) {
    case "commandSafety":
      return renderLazyTab(<CommandSafetyPage />);
    case "contentSecurity":
      return renderLazyTab(<ContentSecurityPage />);
    case "classificationPolicy":
      return renderLazyTab(<AdminClassificationPolicy isAdmin={isAdmin} />);
    case "approvalRule":
      return renderLazyTab(<AdminApprovalRule isAdmin={isAdmin} />);
    case "cedarPolicies":
      return renderLazyTab(<AdminCedarPolicies />);
    case "policyTestBench":
      return renderLazyTab(<AdminCedarPolicies view="bench" />);
    case "runtimeLimits":
      return renderLazyTab(<AdminLimitsAndBudgets />);
    default:
      return undefined;
  }
}

// Knowledge, corporate identity, connectors and agents.
function knowledgeTab(tab: string, props: AdminPanelContentProps, renderLazyTab: RenderLazyTab): ReactNode | undefined {
  const { projects, connectorsTabCtx, toolCatalogTabCtx, knowledgeTabCtx, agentsTabCtx, isAdmin = false } = props;
  switch (tab) {
    case "knowledgeLibrary":
      return renderLazyTab(<KnowledgeAreaPage projects={projects} view="library" isAdmin={isAdmin} />);
    case "knowledgeSources":
      return renderLazyTab(<KnowledgeAreaPage projects={projects} view="sources" />);
    case "knowledgeResearch":
      return renderLazyTab(<KnowledgeAreaPage projects={projects} view="research" />);
    case "knowledgeRelationships":
      return renderLazyTab(<KnowledgeAreaPage projects={projects} view="relationships" isAdmin={isAdmin} />);
    case "knowledgeGraph":
      return renderLazyTab(<KnowledgeAreaPage projects={projects} view="graph" isAdmin={isAdmin} />);
    case "corpIdentity":
      return renderLazyTab(<AdminCorpIdentityTab projects={projects} />);
    case "connectors":
      return renderLazyTab(<AdminConnectorsTab ctx={connectorsTabCtx} />);
    case "databases":
      return renderLazyTab(<AdminDatabasesTab ctx={connectorsTabCtx} />);
    case "toolCatalog":
      return renderLazyTab(<AdminToolCatalogTab ctx={toolCatalogTabCtx} />);
    case "workspaceKnowledge":
      return renderLazyTab(<AdminWorkspaceKnowledgeTab projects={projects} isAdmin={isAdmin} />);
    case "knowledgePackages": case "knowledgeBindings": case "knowledgeChanges":
    case "knowledgeHandbook": case "knowledgeMemory": case "knowledgeEpisodes":
      return renderLazyTab(<KnowledgeAdminPage tab={tab} projects={projects} />);
    case "knowledge":
      return renderLazyTab(<AdminKnowledgeTab ctx={knowledgeTabCtx} />);
    case "agents":
      return renderLazyTab(<AdminAgentsTab ctx={agentsTabCtx} />);
    default:
      return undefined;
  }
}

// Workflows, automation and voice.
function workflowTab(tab: string, props: AdminPanelContentProps, renderLazyTab: RenderLazyTab): ReactNode | undefined {
  const { projects, readJson, schedulersTabCtx, tasksTabCtx, webhooksTabCtx, channelsTabCtx, mcpTabCtx, skillsTabCtx, currentUserId = "" } = props;
  switch (tab) {
    case "effectiveSetup":
      return renderLazyTab(<EffectiveSetupPage />);
    case "workflowList":
      return renderLazyTab(<WorkflowsPage view="list" readJson={readJson} />);
    case "workflowChecks":
      return renderLazyTab(<WorkflowsPage view="checks" readJson={readJson} />);
    case "workflowDesigner":
      return renderLazyTab(<WorkflowsPage view="designer" readJson={readJson} />);
    case "promptCatalog":
      return renderLazyTab(<AdminPromptCatalogTab currentUserId={currentUserId} />);
    case "instructions":
      return renderLazyTab(<InstructionsPage readJson={readJson} />);
    case "schedulers":
      return renderLazyTab(<AdminSchedulersTab ctx={schedulersTabCtx} />);
    case "tasks":
      return renderLazyTab(<AdminTasksTab ctx={tasksTabCtx} />);
    case "webhooks":
      return renderLazyTab(<AdminWebhooksTab ctx={webhooksTabCtx} />);
    case "channels":
      return renderLazyTab(<AdminChannelsTab ctx={channelsTabCtx} />);
    case "mcp":
      return renderLazyTab(<AdminMcpTab ctx={mcpTabCtx} />);
    case "tts":
      return renderLazyTab(<AdminVoiceAndSpeech />);
    case "skills":
      return renderLazyTab(<AdminSkillsTab ctx={skillsTabCtx} />);
    default:
      return undefined;
  }
}

// Usage, observability, operations and the remaining pages.
function observabilityTab(tab: string, props: AdminPanelContentProps, renderLazyTab: RenderLazyTab): ReactNode | undefined {
  const { projects, readJson, brandingTabCtx, brandingEnabled = false, isAdmin = false, currentUserId = "" } = props;
  switch (tab) {
    case "usage":
      return renderLazyTab(<ObservabilityUsagePage projects={projects} readJson={readJson} />);
    case "observabilityOverview":
      return renderLazyTab(<ObservabilityOverviewPage projects={projects} readJson={readJson} />);
    case "operationsCosts":
      return renderLazyTab(<OperationsCostsPage projects={projects} isAdmin={isAdmin} />);
    case "operationsLive":
      return renderLazyTab(<OperationsLivePage projects={projects} isAdmin={isAdmin} currentUserId={currentUserId} />);
    case "observabilityHealth":
      return renderLazyTab(<ObservabilityHealthPage projects={projects} readJson={readJson} />);
    case "observabilityAudit":
      return renderLazyTab(<ObservabilityAuditPage projects={projects} readJson={readJson} />);
    case "complianceAudit":
      return renderLazyTab(<ComplianceAuditPage readJson={readJson} />);
    case "observabilityDecisions":
      return renderLazyTab(<ObservabilityDecisionsPage projects={projects} readJson={readJson} />);
    case "approvalDetail":
      return renderLazyTab(<ApprovalDetailPage projects={projects} />);
    case "observabilityRuns":
      return renderLazyTab(<ObservabilityRunsPage projects={projects} readJson={readJson} />);
    case "branding":
      if (!brandingEnabled) {
        return (
          <div className="admin-panel__empty-state" data-testid="branding-disabled">
            Branding is disabled on this platform.
          </div>
        );
      }
      return renderLazyTab(<AdminBrandingTab ctx={brandingTabCtx} />);
    case "personality":
      return renderLazyTab(<AdminPersonalityTab readJson={readJson} />);
    case "callAgents":
      return renderLazyTab(<AdminCallAgentsTab projects={projects} />);
    default:
      return undefined;
  }
}

export function AdminPanelContent(props: AdminPanelContentProps) {
  const { loadingTab, tabError, onRetry, tab } = props;
  // A panel whose code failed to download shows its own recovery state; the navigation and other
  // panels stay usable, and render errors still reach the area boundary. Keyed by tab, so
  // switching panels starts fresh and revisiting a failed one shows the failure again.
  const renderLazyTab = (node: ReactNode) => (
    <AdminPanelLoadBoundary key={tab}>
      <Suspense fallback={<LoadingState label="this page" variant="page" />}>
        {node}
      </Suspense>
    </AdminPanelLoadBoundary>
  );

  if (loadingTab) {
    return <LoadingState label="this page" variant="page" />;
  }

  if (tabError) {
    return (
      <div className="admin-panel__error" role="alert" data-testid="admin-tab-error">
        {tabError}
        {onRetry ? (
          <>
            {" "}
            <button type="button" className="admin-panel__action-btn" onClick={onRetry}>Retry</button>
          </>
        ) : null}
      </div>
    );
  }

  return platformTab(tab, props, renderLazyTab) ?? governanceTab(tab, props, renderLazyTab) ?? policyTab(tab, props, renderLazyTab)
    ?? knowledgeTab(tab, props, renderLazyTab) ?? workflowTab(tab, props, renderLazyTab)
    ?? observabilityTab(tab, props, renderLazyTab) ?? null;
}
