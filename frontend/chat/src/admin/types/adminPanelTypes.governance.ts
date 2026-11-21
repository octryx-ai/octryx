import type { ApprovalSummary } from "../../chatDecisionTypes";

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
};

// One catalog of events that are actually emitted (knowledge.updated never was; the worker
// monitor's alert was emitted but refused). Mirrors ALLOWED_OUTBOUND_WEBHOOK_EVENTS.
export const OUTBOUND_WEBHOOK_EVENT_OPTIONS = [
  "task.completed",
  "task.failed",
  "approval.requested",
  "session.completed",
  "alert.triggered",
  "worker.monitor.alert",
  // A run or device job got a problem (looping, silent, stalled, …) / it cleared.
  "problem.raised",
  "problem.cleared",
] as const;

export type AdminScenarioProfile = {
  id: string;
  owner_id: string;
  project_id: string | null;
  name: string;
  description: string;
  priority: number;
  match_config: Record<string, unknown>;
  planner_config: Record<string, unknown>;
  execution_config: Record<string, unknown>;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminTab =
  // E6 (central configuration): the Admin home pages that exist before their content does.
  | "adminProblems"
  // Operations › Live: what runs where, what it costs and what is stuck.
  | "operationsLive"
  // Operations › Costs (contract §6): cost and outcome per workflow, work item, run, person or Workspace.
  | "operationsCosts"
  | "adminRules"
  // Admin › Connections, one page per connection with its uses.
  | "adminConnections"
  // Admin › Platform pages built on existing endpoints.
  | "platformVersion"
  | "platformDevices"
  // Custom REST APIs (backend): definitions, operations, grants, connections, and the audited calls.
  | "restApis"
  | "restApiCalls"
  // Plugins: the image's plugins, where they are on, and what the last start did with the folder.
  | "plugins"
  | "users"
  | "identityRoles"
  // Work roles (board 8): Admin › People & sign-in › Roles & functions.
  | "workRoles"
  | "workRoleFunctions"
  | "workRoleAudit"
  | "identityGroups"
  | "identityProviders"
  | "identityAccess"
  | "backupRestore"
  | "projects"
  | "policies"
  | "researchPolicies"
  | "providers"
  | "modelCatalog"
  // Global › Models overview.
  | "modelsOverview"
  // Runtime → Models → Default & fallback and its hidden Policy lists page.
  | "modelOrder"
  | "runtimePolicyLists"
  | "corpIdentity"
  | "knowledge"
  | "workspaceKnowledge"
  // Admin › Knowledge: one page per Knowledge administration section.
  | "knowledgePackages"
  | "knowledgeBindings"
  | "knowledgeChanges"
  | "knowledgeHandbook"
  | "knowledgeMemory"
  | "knowledgeEpisodes"
  | "connectors"
  | "databases"
  | "toolCatalog"
  | "scenarios"
  | "agents"
  | "effectiveSetup"
  | "workflowList"
  | "workflowChecks"
  | "workflowDesigner"
  | "instructions"
  | "promptCatalog"
  | "schedulers"
  | "tasks"
  | "webhooks"
  | "channels"
  | "mcp"
  | "tts"
  | "skills"
  | "usage"
  // Observability area (WP observability audit).
  | "observabilityRuns"
  | "observabilityOverview"
  | "observabilityHealth"
  | "observabilityDecisions"
  // One approval (backend): a hidden page under Decisions, opened by link (`approval=<id>`).
  | "approvalDetail"
  | "observabilityAudit"
  | "branding"
  | "personality"
  | "callAgents"
  // Knowledge area pages rendered from the existing native knowledge views.
  | "knowledgeLibrary"
  | "knowledgeSources"
  | "knowledgeResearch"
  | "knowledgeRelationships"
  | "knowledgeGraph"
  // Runtime pages.
  | "runtimeExecution"
  // Settings → Security: the command risk gate and the content protections.
  | "commandSafety"
  | "contentSecurity"
  // Settings → Governance: the classification policy (with the default level in its header).
  | "classificationPolicy"
  // Settings → Governance: the Cedar policy engine: custom policies and the test bench.
  | "cedarPolicies"
  | "policyTestBench"
  // Settings → Governance: the platform approval rule (four-eyes or single-admin self-approval).
  | "approvalRule"
  | "runtimeLimits"
  | "runtimeCompression";

export type AdminApproval = ApprovalSummary & {
  requestedByName?: string;
  approvedByName?: string;
  sessionTitle?: string;
  sessionStatus?: string;
  projectName?: string;
};
