import type { AdminTab } from "../types/adminPanelTypes.governance";
import {
  loadProjectsTabData,
  loadProvidersTabData,
  loadToolCatalogTabData,
  loadUsersTabData,
} from "./useAdminCoreTabLoader";
import {
  loadBrandingTabData,
  loadChannelsTabData,
  loadConnectorsTabData,
  loadTtsTabData,
  loadWebhookTabData,
} from "./useAdminIntegrationTabLoader";
import { loadMcpTabData } from "./useAdminMcpTabLoader";
import { loadRuntimesTabData } from "./useAdminRuntimeTabLoader";
import type { UseAdminTabLoaderArgs } from "./useAdminTabLoader.types";
import {
  loadSchedulersTabData,
  loadTasksTabData,
} from "./useAdminWorkflowTabLoader";

// The tabs whose entry loads data into the admin shell. Every other panel (Knowledge, Observability, Problems, …)
// loads its own data when it mounts; for those the shell must not show "Loading…" for a moment, because that
// unmounts the panel that just mounted and mounts it again, so it fetches everything twice (perf audit).
const TABS_WITH_SHELL_DATA: ReadonlySet<AdminTab> = new Set<AdminTab>([
  "users", "identityRoles", "identityGroups", "identityAccess", "projects", "providers", "connectors", "databases",
  "toolCatalog", "agents", "runtimeExecution", "runtimeLimits", "schedulers",
  "tasks", "webhooks", "channels", "mcp", "tts", "branding",
]);

export function adminTabLoadsShellData(tab: AdminTab): boolean {
  return TABS_WITH_SHELL_DATA.has(tab);
}

type TabLoader = (args: UseAdminTabLoaderArgs) => Promise<void>;

const loadUsers: TabLoader = (a) => loadUsersTabData(a.readJson, a.setUsers);
const loadConnectors: TabLoader = (a) =>
  loadConnectorsTabData({
    readJson: a.readJson,
    setConnectors: a.setConnectors,
    setToolCatalog: a.setToolCatalog,
    setDatabaseConnectors: a.setDatabaseConnectors,
    setDatabaseTools: a.setDatabaseTools,
    setDatabaseToolForm: a.setDatabaseToolForm,
  });
// The runtime loader reads its own fields (settings drafts, corporate identity) from the loader args.
const loadRuntimes: TabLoader = (a) => loadRuntimesTabData(a as any);

const loadWebhooks: TabLoader = (a) =>
  loadWebhookTabData({
    readJson: a.readJson,
    setWebhooks: a.setWebhooks,
    setOutboundWebhooks: a.setOutboundWebhooks,
    setOutboundWebhookDeliveries: a.setOutboundWebhookDeliveries,
    setConnectorWatchers: a.setConnectorWatchers,
    setConnectorWatcherEvents: a.setConnectorWatcherEvents,
    setConnectorWatcherRules: a.setConnectorWatcherRules,
    setConnectorWatcherRuleDecisions: a.setConnectorWatcherRuleDecisions,
  });

const loadChannels: TabLoader = (a) =>
  loadChannelsTabData({
    readJson: a.readJson,
    setChannels: a.setChannels,
    setChannelSessions: a.setChannelSessions,
    setChannelDeliveryTargets: a.setChannelDeliveryTargets,
    setChannelDeliveryLogs: a.setChannelDeliveryLogs,
  });

const loadMcp: TabLoader = (a) =>
  loadMcpTabData({
    readJson: a.readJson,
    adminProjects: a.adminProjects,
    setAdminProjects: a.setAdminProjects,
    mcpWorkspaceId: a.mcpWorkspaceId,
    setMcpWorkspaceId: a.setMcpWorkspaceId,
    setMcpServers: a.setMcpServers,
    setMcpCatalog: a.setMcpCatalog,
  });

// Tabs without an entry (backup/restore, skills, usage, …) load their own data.
const TAB_LOADERS: Partial<Record<AdminTab, TabLoader>> = {
  users: loadUsers,
  identityRoles: loadUsers,
  identityGroups: loadUsers,
  identityAccess: loadUsers,
  projects: (a) => loadProjectsTabData(a.readJson, a.setAdminProjects),
  providers: (a) =>
    loadProvidersTabData({
      readJson: a.readJson,
      setProviders: a.setProviders,
    }),
  connectors: loadConnectors,
  databases: loadConnectors,
  toolCatalog: (a) => loadToolCatalogTabData(a.readJson, a.setToolCatalog),
  agents: (a) => a.refreshAgentsPanel(),
  runtimeExecution: loadRuntimes,
  runtimeLimits: loadRuntimes,
  schedulers: (a) =>
    loadSchedulersTabData({ readJson: a.readJson, tasks: a.tasks, setSchedulers: a.setSchedulers, setTasks: a.setTasks }),
  tasks: (a) => loadTasksTabData({ readJson: a.readJson, setTasks: a.setTasks, setPanelAgents: a.setPanelAgents }),
  webhooks: loadWebhooks,
  channels: loadChannels,
  mcp: loadMcp,
  tts: (a) => loadTtsTabData({ readJson: a.readJson, setTtsConfig: a.setTtsConfig, setTtsSecrets: a.setTtsSecrets }),
  branding: (a) => loadBrandingTabData({ readJson: a.readJson, setBrandingConfig: a.setBrandingConfig }),
};

export async function loadAdminTabData(
  t: AdminTab,
  args: UseAdminTabLoaderArgs,
) {
  const loader = TAB_LOADERS[t];
  if (loader) await loader(args);
}
