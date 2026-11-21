import type { Dispatch, SetStateAction } from "react";

export type ProjectOptionRow = {
  id: string;
  name: string;
};

export type AgentModeRow = {
  id?: string;
  key: string;
  name: string;
};

export type AdminWebhookRow = {
  id: string;
  project_id: string;
  name: string;
  description?: string | null;
  source_type: string;
  agent_type: string;
  // Write-only: the secret is never listed, only whether one is stored.
  has_secret?: boolean;
  is_active: boolean;
};

export type AdminOutboundWebhookRow = {
  id: string;
  project_id: string | null;
  name: string;
  url?: string;
  url_masked: string;
  event_types: string[];
  is_active: boolean;
  secret_configured?: boolean;
  last_delivery_status: string | null;
  last_delivery_at?: string | null;
  last_error: string | null;
  signing_secret?: string;
};

export type AdminOutboundWebhookDeliveryRow = {
  id: string;
  webhook_id: string;
  /** The destination's name, never a sliced id. */
  webhook_name?: string | null;
  project_id?: string | null;
  event_type: string;
  retry_count?: number;
  status: string;
  http_status: number | null;
  request_id: string | null;
  response_body?: string | null;
  error: string | null;
  delivered_at?: string | null;
  created_at: string | null;
};

export type AdminConnectorWatcherRow = {
  id: string;
  project_id?: string | null;
  connector_name: string;
  connector_instance: string;
  provider_type: string;
  name: string;
  description?: string | null;
  mode: string;
  event_types: string[];
  status: string;
  last_event_id?: string | null;
  last_event_at?: string | null;
  last_cursor?: string | null;
  dead_letter_count: number;
  secret_configured?: boolean;
  is_active: boolean;
  health?: {
    last_event_status?: string | null;
    last_event_at?: string | null;
    dead_letter_count?: number;
    duplicate_count?: number;
    failure_count?: number;
    rate_limited_count?: number;
    retry_count?: number;
    replay_count?: number;
    out_of_order_count?: number;
  };
};

export type AdminConnectorWatcherEventRow = {
  id: string;
  watcher_id: string;
  connector_name: string;
  connector_instance: string;
  provider_type: string;
  event_type: string;
  external_id?: string | null;
  actor?: string | null;
  received_at?: string | null;
  status: string;
  duplicate_of_event_id?: string | null;
  attempts: number;
  next_retry_at?: string | null;
  error?: string | null;
  scope?: Record<string, unknown>;
  normalized?: Record<string, unknown>;
  processing_result?: Record<string, unknown>;
};

export type AdminConnectorWatcherRuleRow = {
  id: string;
  project_id?: string | null;
  name: string;
  description?: string | null;
  connector_name?: string | null;
  connector_instance?: string | null;
  event_types: string[];
  conditions: { all?: { field: string; operator: string; value?: unknown }[] };
  actions: { type: string; config?: Record<string, unknown> }[];
  enforcement: Record<string, unknown>;
  override_roles: string[];
  rate_limit: Record<string, unknown>;
  priority: number;
  status: string;
  is_active: boolean;
};

export type AdminConnectorWatcherRuleDecisionRow = {
  id: string;
  rule_id: string;
  event_id: string;
  watcher_id: string;
  decision: string;
  matched: boolean;
  actions: { type: string; config?: Record<string, unknown> }[];
  reasons: string[];
  action_results: { action: string; status: string; effect?: string }[];
  created_at?: string | null;
};

export type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

export type AdminWebhooksTabProps = {
  projects: ProjectOptionRow[];
  availableAgentModes: AgentModeRow[];
  webhooks: AdminWebhookRow[];
  showCreateWebhook: boolean;
  setShowCreateWebhook: Dispatch<SetStateAction<boolean>>;
  editingWebhookId: string | null;
  setEditingWebhookId: Dispatch<SetStateAction<string | null>>;
  webhookFormName: string;
  setWebhookFormName: Dispatch<SetStateAction<string>>;
  webhookFormDescription: string;
  setWebhookFormDescription: Dispatch<SetStateAction<string>>;
  webhookFormProjectId: string;
  setWebhookFormProjectId: Dispatch<SetStateAction<string>>;
  webhookFormSourceType: string;
  setWebhookFormSourceType: Dispatch<SetStateAction<string>>;
  webhookFormAgentType: string;
  setWebhookFormAgentType: Dispatch<SetStateAction<string>>;
  webhookFormActive: boolean;
  setWebhookFormActive: Dispatch<SetStateAction<boolean>>;
  webhookFormLoading: boolean;
  setWebhookFormLoading: Dispatch<SetStateAction<boolean>>;
  webhookFormError: string | null;
  setWebhookFormError: Dispatch<SetStateAction<string | null>>;
  outboundWebhooks: AdminOutboundWebhookRow[];
  showCreateOutboundWebhook: boolean;
  setShowCreateOutboundWebhook: Dispatch<SetStateAction<boolean>>;
  editingOutboundWebhookId: string | null;
  setEditingOutboundWebhookId: Dispatch<SetStateAction<string | null>>;
  outboundWebhookFormName: string;
  setOutboundWebhookFormName: Dispatch<SetStateAction<string>>;
  outboundWebhookFormUrl: string;
  setOutboundWebhookFormUrl: Dispatch<SetStateAction<string>>;
  outboundWebhookFormProjectId: string;
  setOutboundWebhookFormProjectId: Dispatch<SetStateAction<string>>;
  outboundWebhookFormEvents: string[];
  setOutboundWebhookFormEvents: Dispatch<SetStateAction<string[]>>;
  outboundWebhookFormLoading: boolean;
  setOutboundWebhookFormLoading: Dispatch<SetStateAction<boolean>>;
  outboundWebhookFormError: string | null;
  setOutboundWebhookFormError: Dispatch<SetStateAction<string | null>>;
  createdOutboundSigningSecret: string | null;
  setCreatedOutboundSigningSecret: Dispatch<SetStateAction<string | null>>;
  showOutboundDeliveries: boolean;
  setShowOutboundDeliveries: Dispatch<SetStateAction<boolean>>;
  outboundWebhookDeliverySearch: string;
  setOutboundWebhookDeliverySearch: Dispatch<SetStateAction<string>>;
  outboundWebhookDeliveries: AdminOutboundWebhookDeliveryRow[];
  filteredOutboundWebhookDeliveries: AdminOutboundWebhookDeliveryRow[];
  connectorWatchers: AdminConnectorWatcherRow[];
  connectorWatcherEvents: AdminConnectorWatcherEventRow[];
  connectorWatcherRules: AdminConnectorWatcherRuleRow[];
  connectorWatcherRuleDecisions: AdminConnectorWatcherRuleDecisionRow[];
  outboundWebhookEventOptions: readonly string[];
  formatDateTime: (value: string | null | undefined) => string;
  readJson: ReadJsonFn;
  reloadWebhooksTab: () => void;
};
