import type { ApprovalSummary } from "../../chatDecisionTypes";

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
};

// Only events that are actually emitted; mirrors ALLOWED_OUTBOUND_WEBHOOK_EVENTS.
export const OUTBOUND_WEBHOOK_EVENT_OPTIONS = [
  "task.completed",
  "task.failed",
  "approval.requested",
  "session.completed",
  "alert.triggered",
  "worker.monitor.alert",
  "problem.raised",
  "problem.cleared",
] as const;

export type AdminTab =
  | "adminProblems"
  | "operationsLive"
  | "operationsCosts"
  | "adminRules"
  | "adminConnections"
  | "platformVersion"
  | "platformDevices"
  | "restApis"
  | "restApiCalls"
  | "plugins"
  | "users"
  | "identityRoles"
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
  | "modelsOverview"
  | "modelOrder"
  | "runtimePolicyLists"
  | "corpIdentity"
  | "knowledge"
  | "workspaceKnowledge"
  | "knowledgePackages"
  | "knowledgeBindings"
  | "knowledgeChanges"
  | "knowledgeHandbook"
  | "knowledgeMemory"
  | "knowledgeEpisodes"
  | "connectors"
  | "databases"
  | "toolCatalog"
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
  | "observabilityRuns"
  | "observabilityOverview"
  | "observabilityHealth"
  | "observabilityDecisions"
  | "approvalDetail"
  | "observabilityAudit"
  | "complianceAudit"
  | "branding"
  | "personality"
  | "callAgents"
  | "knowledgeLibrary"
  | "knowledgeSources"
  | "knowledgeResearch"
  | "knowledgeRelationships"
  | "knowledgeGraph"
  | "runtimeExecution"
  | "commandSafety"
  | "contentSecurity"
  | "classificationPolicy"
  | "cedarPolicies"
  | "policyTestBench"
  | "approvalRule"
  | "runtimeLimits";

export type AdminApproval = ApprovalSummary & {
  requestedByName?: string;
  approvedByName?: string;
  sessionTitle?: string;
  sessionStatus?: string;
  projectName?: string;
};
