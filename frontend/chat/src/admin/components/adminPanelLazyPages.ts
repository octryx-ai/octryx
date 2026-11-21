// The admin panels, each loaded on first use through the marked loader.
import { lazyAdminPanel } from "./adminPanelLoad";

export const ObservabilityRunsPage = lazyAdminPanel(async () => {
  const module = await import("./observability/ObservabilityRunsPage");
  return { default: module.ObservabilityRunsPage };
});
export const ObservabilityOverviewPage = lazyAdminPanel(async () => {
  const module = await import("./observability/ObservabilityOverviewPage");
  return { default: module.ObservabilityOverviewPage };
});
export const ObservabilityHealthPage = lazyAdminPanel(async () => {
  const module = await import("./observability/ObservabilityHealthPage");
  return { default: module.ObservabilityHealthPage };
});
export const ObservabilityAuditPage = lazyAdminPanel(async () => {
  const module = await import("./observability/ObservabilityAuditPage");
  return { default: module.ObservabilityAuditPage };
});
export const ApprovalDetailPage = lazyAdminPanel(async () => {
  const module = await import("../../chat/approval/ApprovalDetailPage");
  return { default: module.ApprovalDetailPage };
});
export const ObservabilityDecisionsPage = lazyAdminPanel(async () => {
  const module = await import("./observability/ObservabilityDecisionsPage");
  return { default: module.ObservabilityDecisionsPage };
});
export const OperationsCostsPage = lazyAdminPanel(async () => ({ default: (await import("./operations/OperationsCostsPage")).OperationsCostsPage }));
export const OperationsLivePage = lazyAdminPanel(async () => ({ default: (await import("./operations/OperationsLivePage")).OperationsLivePage }));
export const AdminProblemsPage = lazyAdminPanel(async () => ({ default: (await import("./problems/AdminProblemsPage")).AdminProblemsPage }));
export const RestApisPage = lazyAdminPanel(async () => ({ default: (await import("./restApis/RestApisPage")).RestApisPage }));
export const RestApiCallsPage = lazyAdminPanel(async () => ({ default: (await import("./restApis/RestApiCallsPage")).RestApiCallsPage }));
export const ConnectionsPage = lazyAdminPanel(async () => ({ default: (await import("./connections/ConnectionsPage")).ConnectionsPage }));
export const WorkRolesPage = lazyAdminPanel(async () => ({ default: (await import("./workRoles/WorkRolesPage")).WorkRolesPage }));
export const WorkFunctionsPage = lazyAdminPanel(async () => ({ default: (await import("./workRoles/WorkFunctionsPage")).WorkFunctionsPage }));
export const WorkRolesAuditPage = lazyAdminPanel(async () => ({ default: (await import("./workRoles/WorkRolesAuditPage")).WorkRolesAuditPage }));
export const PlatformPage = lazyAdminPanel(async () => ({ default: (await import("./platform/PlatformPage")).PlatformPage }));
export const PluginsPage = lazyAdminPanel(async () => ({ default: (await import("./plugins/PluginsPage")).PluginsPage }));
export const EffectiveSetupPage = lazyAdminPanel(async () => {
  const module = await import("./agentsWorkflows/effectiveSetup/EffectiveSetupPage");
  return { default: module.EffectiveSetupPage };
});
export const WorkflowsPage = lazyAdminPanel(async () => {
  const module = await import("./agentsWorkflows/workflows/WorkflowsPage");
  return { default: module.WorkflowsPage };
});
export const InstructionsPage = lazyAdminPanel(async () => {
  const module = await import("./agentsWorkflows/instructions/InstructionsPage");
  return { default: module.InstructionsPage };
});
export const AdminPromptCatalogTab = lazyAdminPanel(async () => {
  const module = await import("./promptCatalog/AdminPromptCatalogTab");
  return { default: module.AdminPromptCatalogTab };
});
export const AdminAgentsTab = lazyAdminPanel(async () => {
  const module = await import("./AdminAgentsTab");
  return { default: module.AdminAgentsTab };
});
export const AdminWorkspaceKnowledgeTab = lazyAdminPanel(async () => {
  const module = await import("./workspaceKnowledge/AdminWorkspaceKnowledgeTab");
  return { default: module.AdminWorkspaceKnowledgeTab };
});
// Admin › Knowledge: one page per Knowledge administration section.
export const KnowledgeAdminPage = lazyAdminPanel(async () => {
  const module = await import("./workspaceKnowledge/KnowledgeAdminPage");
  return { default: module.KnowledgeAdminPage };
});
export const AdminCorpIdentityTab = lazyAdminPanel(async () => {
  const module = await import("./AdminCorpIdentityTab");
  return { default: module.AdminCorpIdentityTab };
});
export const AdminBrandingTab = lazyAdminPanel(async () => {
  const module = await import("./AdminBrandingTab");
  return { default: module.AdminBrandingTab };
});
export const AdminBackupRestoreTab = lazyAdminPanel(async () => {
  const module = await import("./AdminBackupRestoreTab");
  return { default: module.AdminBackupRestoreTab };
});
export const AdminCallAgentsTab = lazyAdminPanel(async () => {
  const module = await import("./AdminCallAgentsTab");
  return { default: module.AdminCallAgentsTab };
});
export const AdminPersonalityTab = lazyAdminPanel(async () => {
  const module = await import("./AdminPersonalityTab");
  return { default: module.AdminPersonalityTab };
});
export const AdminChannelsTab = lazyAdminPanel(async () => {
  const module = await import("./AdminChannelsTab");
  return { default: module.AdminChannelsTab };
});
export const AdminConnectorsTab = lazyAdminPanel(async () => {
  const module = await import("./AdminConnectorsTab");
  return { default: module.AdminConnectorsTab };
});
export const AdminDatabasesTab = lazyAdminPanel(async () => {
  const module = await import("./databases/AdminDatabasesTab");
  return { default: module.AdminDatabasesTab };
});
export const AdminKnowledgeTab = lazyAdminPanel(async () => {
  const module = await import("./AdminKnowledgeTab");
  return { default: module.AdminKnowledgeTab };
});
export const AdminMcpTab = lazyAdminPanel(async () => {
  const module = await import("./AdminMcpTab");
  return { default: module.AdminMcpTab };
});
export const ToolApprovalsPage = lazyAdminPanel(async () => {
  const module = await import("./toolApprovals/ToolApprovalsPage");
  return { default: module.ToolApprovalsPage };
});
export const AdminResearchPoliciesTab = lazyAdminPanel(async () => {
  const module = await import("./AdminResearchPoliciesTab");
  return { default: module.AdminResearchPoliciesTab };
});
export const AdminProjectsTab = lazyAdminPanel(async () => {
  const module = await import("./AdminProjectsTab");
  return { default: module.AdminProjectsTab };
});
export const AdminModelCatalog = lazyAdminPanel(async () => {
  const module = await import("./modelCatalog/AdminModelCatalog");
  return { default: module.AdminModelCatalog };
});
export const AdminModelsOverview = lazyAdminPanel(async () => {
  const module = await import("./modelsOverview/AdminModelsOverview");
  return { default: module.AdminModelsOverview };
});
export const AdminDefaultAndFallback = lazyAdminPanel(async () => {
  const module = await import("./modelSelection/AdminDefaultAndFallback");
  return { default: module.AdminDefaultAndFallback };
});
export const AdminLimitsAndBudgets = lazyAdminPanel(async () => {
  const module = await import("./limits/AdminLimitsAndBudgets");
  return { default: module.AdminLimitsAndBudgets };
});
export const AdminPolicyListsSection = lazyAdminPanel(async () => {
  const module = await import("./AdminPolicyListsSection");
  return { default: module.AdminPolicyListsSection };
});
export const AdminProvidersTab = lazyAdminPanel(async () => {
  const module = await import("./AdminProvidersTab");
  return { default: module.AdminProvidersTab };
});
export const AdminRuntimesTab = lazyAdminPanel(async () => {
  const module = await import("./AdminRuntimesTab");
  return { default: module.AdminRuntimesTab };
});
export const ContentSecurityPage = lazyAdminPanel(async () => {
  const module = await import("./contentSecurity/ContentSecurityPage");
  return { default: module.ContentSecurityPage };
});
export const CommandSafetyPage = lazyAdminPanel(async () => {
  const module = await import("./commandSafety/CommandSafetyPage");
  return { default: module.CommandSafetyPage };
});
export const AdminClassificationPolicy = lazyAdminPanel(async () => {
  const module = await import("./dataClassification/AdminClassificationPolicy");
  return { default: module.AdminClassificationPolicy };
});
export const AdminApprovalRule = lazyAdminPanel(async () => {
  const module = await import("./approvalRule/AdminApprovalRule");
  return { default: module.AdminApprovalRule };
});
export const AdminCedarPolicies = lazyAdminPanel(async () => {
  const module = await import("./policyEngine/AdminCedarPolicies");
  return { default: module.AdminCedarPolicies };
});
export const AdminScenariosTab = lazyAdminPanel(async () => {
  const module = await import("./AdminScenariosTab");
  return { default: module.AdminScenariosTab };
});
export const AdminSkillsTab = lazyAdminPanel(async () => {
  const module = await import("./AdminSkillsTab");
  return { default: module.AdminSkillsTab };
});
export const AdminSchedulersTab = lazyAdminPanel(async () => {
  const module = await import("./AdminSchedulersTab");
  return { default: module.AdminSchedulersTab };
});
export const AdminTasksTab = lazyAdminPanel(async () => {
  const module = await import("./AdminTasksTab");
  return { default: module.AdminTasksTab };
});
export const AdminToolCatalogTab = lazyAdminPanel(async () => {
  const module = await import("./AdminToolCatalogTab");
  return { default: module.AdminToolCatalogTab };
});
export const AdminVoiceAndSpeech = lazyAdminPanel(async () => {
  const module = await import("./voice/AdminVoiceAndSpeech");
  return { default: module.AdminVoiceAndSpeech };
});
export const ObservabilityUsagePage = lazyAdminPanel(async () => {
  const module = await import("./observability/ObservabilityUsagePage");
  return { default: module.ObservabilityUsagePage };
});
export const AdminUsersTab = lazyAdminPanel(async () => {
  const module = await import("./AdminUsersTab");
  return { default: module.AdminUsersTab };
});
export const AdminWebhooksTab = lazyAdminPanel(async () => {
  const module = await import("./AdminWebhooksTab");
  return { default: module.AdminWebhooksTab };
});

export const KnowledgeAreaPage = lazyAdminPanel(async () => {
  const module = await import("../../chat/knowledge/KnowledgeAreaWorkspace");
  return { default: module.KnowledgeAreaPage };
});
