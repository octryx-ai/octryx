import type { Dispatch, SetStateAction } from "react";
import type { AdminAgentMode, PanelAgent } from "../types/adminPanelTypes.agents";
import type { AdminChannelRow as AdminChannel } from "../components/channelTypes";
import type { AdminConnector, AdminDatabaseConnector, AdminDatabaseTool, AdminModel, AdminProvider, AdminToolCatalogEntry, AdminUser } from "../types/adminPanelTypes.usersProviders";
import type { AdminCorpIdentityListResponse, AdminRuntime, AdminRuntimeSettings } from "../types/adminPanelTypes.runtimeCorp";
import type { MCPCatalogEntry, MCPServer } from "../components/mcpTypes";
import type {
  AdminChannelDeliveryLogRow as AdminChannelDeliveryLog,
  AdminChannelDeliveryTargetRow as AdminChannelDeliveryTarget,
  AdminChannelSessionRow as AdminChannelSession,
} from "../components/channelTypes";
import type {
  AdminConnectorWatcherEventRow as AdminConnectorWatcherEvent,
  AdminConnectorWatcherRuleDecisionRow as AdminConnectorWatcherRuleDecision,
  AdminConnectorWatcherRuleRow as AdminConnectorWatcherRule,
  AdminConnectorWatcherRow as AdminConnectorWatcher,
  AdminOutboundWebhookDeliveryRow as AdminOutboundWebhookDelivery,
  AdminOutboundWebhookRow as AdminOutboundWebhook,
  AdminWebhookRow as AdminWebhook,
} from "../components/webhookTypes";
import type { AdminProjectQuality } from "../types/projectQualityTypes";
import type { PanelScheduler } from "../types/projectQualityTypes.design";
import type { PanelTaskRow } from "../components/taskTypes";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type TtsConfigPayload = {
  enabled: boolean;
  default_voice: string;
  default_speed: number;
  providers: {
    id: string;
    name: string;
    voices: string[];
    has_key: boolean;
    key_required?: boolean;
    enabled: boolean;
    priority: number;
  }[];
};

export type DatabaseToolFormPayload = {
  connector_id: string;
  tool_name: string;
  display_name: string;
  description: string;
  sql_template: string;
  parameters_schema: string;
  row_level_security_rules: string;
  allowed_roles: string;
  max_rows: string;
  timeout_seconds: string;
  is_active: boolean;
};

export type UseAdminTabLoaderArgs = {
  readJson: ReadJsonFn;
  setLoadingTab: Dispatch<SetStateAction<boolean>>;
  setTabError: Dispatch<SetStateAction<string | null>>;
  setUsers: Dispatch<SetStateAction<AdminUser[]>>;
  setAdminProjects: Dispatch<SetStateAction<AdminProjectQuality[]>>;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  setToolCatalog: Dispatch<SetStateAction<AdminToolCatalogEntry[]>>;
  setConnectors: Dispatch<SetStateAction<AdminConnector[]>>;
  setDatabaseConnectors: Dispatch<SetStateAction<AdminDatabaseConnector[]>>;
  setDatabaseTools: Dispatch<SetStateAction<AdminDatabaseTool[]>>;
  setDatabaseToolForm: Dispatch<SetStateAction<DatabaseToolFormPayload>>;
  refreshAgentsPanel: () => Promise<void>;
  providers: AdminProvider[];
  setRuntimes: Dispatch<SetStateAction<AdminRuntime[]>>;
  setRuntimeSettings: Dispatch<SetStateAction<AdminRuntimeSettings>>;
  setRuntimeGlobalOutputDraft: Dispatch<SetStateAction<string>>;
  setRuntimeDefaultModelDraft: Dispatch<SetStateAction<string>>;
  setRuntimeAuthOidcOnlyDraft: Dispatch<SetStateAction<boolean>>;
  setRuntimeExecutionProviderDraft: Dispatch<SetStateAction<"host" | "docker">>;
  setRuntimeExecutionDockerImageDraft: Dispatch<SetStateAction<string>>;
  setRuntimeExecutionDockerNetworkDraft: Dispatch<
    SetStateAction<"none" | "bridge" | "host">
  >;
  setRuntimeExecutionAllowHostFallback: Dispatch<SetStateAction<boolean>>;
  setRuntimeWorkspaceBaseDirDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceMaxAgeDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceStorageBackendDraft: Dispatch<
    SetStateAction<AdminRuntimeSettings["session_workspace_storage_backend"]>
  >;
  setRuntimeWorkspaceStorageBucketDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceStoragePrefixDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceSyncExcludedDirsDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceSyncExcludedGlobsDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceSyncMaxFileSizeDraft: Dispatch<SetStateAction<string>>;
  setRuntimeWorkspaceSyncMaxFileCountDraft: Dispatch<SetStateAction<string>>;
  setRuntimeOfficeTemplatesDraft: Dispatch<
    SetStateAction<AdminRuntimeSettings["office_template_library"]>
  >;
  applyCorpIdentityListPayload: (
    payload: AdminCorpIdentityListResponse,
  ) => void;
  setRuntimeLlmSecurityTimeoutDraft: Dispatch<SetStateAction<string>>;
  setRuntimeLlmSecurityReviewThresholdDraft: Dispatch<SetStateAction<string>>;
  setRuntimeLlmSecurityDenyThresholdDraft: Dispatch<SetStateAction<string>>;
  setRuntimeSecurityAnalyzerChainDraft: Dispatch<SetStateAction<string>>;
  setRuntimeApproxCharsDraft: Dispatch<SetStateAction<string>>;
  setRuntimeTraceMaxStringDraft: Dispatch<SetStateAction<string>>;
  setRuntimeTraceMaxListDraft: Dispatch<SetStateAction<string>>;
  setRuntimeTraceMaxDictDraft: Dispatch<SetStateAction<string>>;
  setRuntimeScriptOutputDraft: Dispatch<SetStateAction<string>>;
  setRuntimeRequestTimeoutDraft: Dispatch<SetStateAction<string>>;
  setRuntimeSessionCostLimitDraft: Dispatch<SetStateAction<string>>;
  setRuntimeRequestCostLimitDraft: Dispatch<SetStateAction<string>>;
  tasks: PanelTaskRow[];
  setSchedulers: Dispatch<SetStateAction<PanelScheduler[]>>;
  setTasks: Dispatch<SetStateAction<PanelTaskRow[]>>;
  setPanelAgents: Dispatch<SetStateAction<PanelAgent[]>>;
  setWebhooks: Dispatch<SetStateAction<AdminWebhook[]>>;
  setOutboundWebhooks: Dispatch<SetStateAction<AdminOutboundWebhook[]>>;
  setOutboundWebhookDeliveries: Dispatch<
    SetStateAction<AdminOutboundWebhookDelivery[]>
  >;
  setConnectorWatchers: Dispatch<SetStateAction<AdminConnectorWatcher[]>>;
  setConnectorWatcherEvents: Dispatch<
    SetStateAction<AdminConnectorWatcherEvent[]>
  >;
  setConnectorWatcherRules: Dispatch<SetStateAction<AdminConnectorWatcherRule[]>>;
  setConnectorWatcherRuleDecisions: Dispatch<
    SetStateAction<AdminConnectorWatcherRuleDecision[]>
  >;
  setChannels: Dispatch<SetStateAction<AdminChannel[]>>;
  setChannelSessions: Dispatch<SetStateAction<AdminChannelSession[]>>;
  setChannelDeliveryTargets: Dispatch<
    SetStateAction<AdminChannelDeliveryTarget[]>
  >;
  setChannelDeliveryLogs: Dispatch<SetStateAction<AdminChannelDeliveryLog[]>>;
  mcpWorkspaceId: string;
  setMcpWorkspaceId: Dispatch<SetStateAction<string>>;
  setMcpServers: Dispatch<SetStateAction<MCPServer[]>>;
  setMcpCatalog: Dispatch<SetStateAction<MCPCatalogEntry[]>>;
  setTtsConfig: Dispatch<SetStateAction<TtsConfigPayload | null>>;
  setTtsSecrets: Dispatch<SetStateAction<Record<string, string>>>;
  adminProjects: AdminProjectQuality[];
  providerModels: Record<string, AdminModel[]>;
  setProviderModels: Dispatch<SetStateAction<Record<string, AdminModel[]>>>;
  setBrandingConfig: Dispatch<
    SetStateAction<{
      app_name: string;
      logo_url: string;
      logo_svg: string;
    } | null>
  >;
  setAgentModes: Dispatch<SetStateAction<AdminAgentMode[]>>;
};
