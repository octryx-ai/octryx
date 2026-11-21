import type { Dispatch, SetStateAction } from "react";
import type {
  AdminChannelDeliveryLogRow as AdminChannelDeliveryLog,
  AdminChannelDeliveryTargetRow as AdminChannelDeliveryTarget,
  AdminChannelRow as AdminChannel,
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
import type { AdminConnector, AdminDatabaseConnector, AdminDatabaseTool, AdminToolCatalogEntry } from "../types/adminPanelTypes.usersProviders";
import { DEFAULT_BRANDING } from "../../chat/defaultBranding";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type LoadConnectorsTabDataArgs = {
  readJson: ReadJsonFn;
  setConnectors: Dispatch<SetStateAction<AdminConnector[]>>;
  setToolCatalog: Dispatch<SetStateAction<AdminToolCatalogEntry[]>>;
  setDatabaseConnectors: Dispatch<SetStateAction<AdminDatabaseConnector[]>>;
  setDatabaseTools: Dispatch<SetStateAction<AdminDatabaseTool[]>>;
  setDatabaseToolForm: Dispatch<
    SetStateAction<{
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
    }>
  >;
};

export async function loadConnectorsTabData({
  readJson,
  setConnectors,
  setToolCatalog,
  setDatabaseConnectors,
  setDatabaseTools,
  setDatabaseToolForm,
}: LoadConnectorsTabDataArgs) {
  const [connectorData, catalogData, databaseConnectorData, databaseToolData] =
    await Promise.all([
      readJson<AdminConnector[]>("/admin/chat/api/panel/connectors"),
      readJson<AdminToolCatalogEntry[]>("/admin/chat/api/panel/tool-catalog"),
      readJson<AdminDatabaseConnector[]>(
        "/admin/chat/api/panel/database-connectors",
      ),
      readJson<AdminDatabaseTool[]>("/admin/chat/api/panel/database-tools"),
    ]);
  setConnectors(connectorData);
  setToolCatalog(catalogData);
  setDatabaseConnectors(databaseConnectorData);
  setDatabaseTools(databaseToolData);
  setDatabaseToolForm((prev) => ({
    ...prev,
    connector_id: prev.connector_id || databaseConnectorData[0]?.id || "",
  }));
}

type LoadWebhookTabDataArgs = {
  readJson: ReadJsonFn;
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
};

export async function loadWebhookTabData({
  readJson,
  setWebhooks,
  setOutboundWebhooks,
  setOutboundWebhookDeliveries,
  setConnectorWatchers,
  setConnectorWatcherEvents,
  setConnectorWatcherRules,
  setConnectorWatcherRuleDecisions,
}: LoadWebhookTabDataArgs) {
  const [
    data,
    outboundData,
    outboundDeliveryData,
    connectorWatcherData,
    connectorWatcherEventData,
    connectorWatcherRuleData,
    connectorWatcherRuleDecisionData,
  ] = await Promise.all([
    readJson<AdminWebhook[]>("/admin/chat/api/panel/webhooks"),
    readJson<AdminOutboundWebhook[]>("/admin/chat/api/panel/outbound-webhooks"),
    readJson<AdminOutboundWebhookDelivery[]>(
      "/admin/chat/api/panel/outbound-webhook-deliveries?limit=20",
    ),
    readJson<AdminConnectorWatcher[]>(
      "/admin/chat/api/panel/connector-watchers",
    ),
    readJson<AdminConnectorWatcherEvent[]>(
      "/admin/chat/api/panel/connector-watcher-events?limit=20",
    ),
    readJson<AdminConnectorWatcherRule[]>(
      "/admin/chat/api/panel/connector-watcher-rules",
    ),
    readJson<AdminConnectorWatcherRuleDecision[]>(
      "/admin/chat/api/panel/connector-watcher-rule-decisions?limit=20",
    ),
  ]);
  setWebhooks(data);
  setOutboundWebhooks(outboundData);
  setOutboundWebhookDeliveries(outboundDeliveryData);
  setConnectorWatchers(connectorWatcherData);
  setConnectorWatcherEvents(connectorWatcherEventData);
  setConnectorWatcherRules(connectorWatcherRuleData);
  setConnectorWatcherRuleDecisions(connectorWatcherRuleDecisionData);
}

type LoadChannelsTabDataArgs = {
  readJson: ReadJsonFn;
  setChannels: Dispatch<SetStateAction<AdminChannel[]>>;
  setChannelSessions: Dispatch<SetStateAction<AdminChannelSession[]>>;
  setChannelDeliveryTargets: Dispatch<
    SetStateAction<AdminChannelDeliveryTarget[]>
  >;
  setChannelDeliveryLogs: Dispatch<SetStateAction<AdminChannelDeliveryLog[]>>;
};

export async function loadChannelsTabData({
  readJson,
  setChannels,
  setChannelSessions,
  setChannelDeliveryTargets,
  setChannelDeliveryLogs,
}: LoadChannelsTabDataArgs) {
  const [channelData, sessionData, deliveryTargetData, deliveryLogData] =
    await Promise.all([
      readJson<AdminChannel[]>("/admin/chat/api/panel/channels"),
      readJson<AdminChannelSession[]>(
        "/admin/chat/api/panel/channel-sessions?limit=50",
      ),
      readJson<AdminChannelDeliveryTarget[]>(
        "/admin/chat/api/panel/channel-delivery-targets",
      ),
      readJson<AdminChannelDeliveryLog[]>(
        "/admin/chat/api/panel/channel-delivery-log?limit=100",
      ),
    ]);
  setChannels(channelData);
  setChannelSessions(sessionData);
  setChannelDeliveryTargets(deliveryTargetData);
  setChannelDeliveryLogs(deliveryLogData);
}

type TtsProviderConfig = {
  id: string;
  name: string;
  voices: string[];
  has_key: boolean;
  enabled: boolean;
  priority: number;
};

type TtsConfig = {
  enabled: boolean;
  default_voice: string;
  default_speed: number;
  providers: TtsProviderConfig[];
};

type LoadTtsTabDataArgs = {
  readJson: ReadJsonFn;
  setTtsConfig: Dispatch<SetStateAction<TtsConfig | null>>;
  setTtsSecrets: Dispatch<SetStateAction<Record<string, string>>>;
};

export async function loadTtsTabData({
  readJson,
  setTtsConfig,
  setTtsSecrets,
}: LoadTtsTabDataArgs) {
  const [configData, secretsData] = await Promise.all([
    readJson<TtsConfig>("/admin/chat/api/v1/tts/providers"),
    readJson<Record<string, string>>("/admin/chat/api/panel/tts/config").catch(
      () => ({}),
    ),
  ]);
  setTtsConfig(configData);
  setTtsSecrets(secretsData);
}

type LoadBrandingTabDataArgs = {
  readJson: ReadJsonFn;
  setBrandingConfig: Dispatch<
    SetStateAction<{
      app_name: string;
      logo_url: string;
      logo_svg: string;
    } | null>
  >;
};

export async function loadBrandingTabData({
  readJson,
  setBrandingConfig,
}: LoadBrandingTabDataArgs) {
  const data = await readJson<{
    app_name: string;
    logo_url: string;
    logo_svg: string;
  }>("/admin/chat/api/panel/branding").catch(() => DEFAULT_BRANDING);
  setBrandingConfig(data);
}
