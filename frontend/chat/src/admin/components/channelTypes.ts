import type { Dispatch, ReactNode, SetStateAction } from "react";

export type ProjectOptionRow = {
  id: string;
  name: string;
};

export type AdminChannelConfigFieldRow = {
  name: string;
  type: string;
  required?: boolean;
  default?: unknown;
  description?: string;
  options?: string[];
  secret?: boolean;
};

export type AdminChannelRow = {
  id: number | null;
  plugin_id: string;
  name: string;
  description: string;
  project_id: string | null;
  project_name: string | null;
  enabled: boolean;
  config: Record<string, unknown>;
  status: string;
  updated_at: string | null;
  config_fields: AdminChannelConfigFieldRow[];
  webhook_url?: string | null;
  // Secrets are write-only: the server reports only whether one is stored.
  secret_fields?: Record<string, { has_value: boolean }>;
};

export type AdminChannelSessionRow = {
  id: string;
  status: string;
  project_id: string | null;
  project_name: string | null;
  agent_type: string;
  title: string;
  channel: string | null;
  channel_id: string | null;
  channel_name: string | null;
  channel_key: string | null;
  conversation_id: string | null;
  channel_type: string | null;
  sender_id: string | null;
  message_count: number;
  started_at: string | null;
  ended_at: string | null;
  last_message_at: string | null;
};

export type AdminChannelDeliveryTargetRow = {
  id: string;
  user_id: string | null;
  project_id: string | null;
  event_type: string;
  channel_type: string;
  channel_config_id: number | null;
  target: string;
  template_id: string | null;
  is_active: boolean;
  created_by: string;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminChannelDeliveryLogRow = {
  id: string;
  notification_id: string | null;
  subscription_id: string | null;
  template_id: string | null;
  user_id: string | null;
  project_id: string | null;
  project_name?: string | null;
  event_type: string;
  channel_type: string;
  channel_config_id: number | null;
  target: string;
  subject: string | null;
  body: string | null;
  status: string;
  retry_count: number;
  next_retry_at: string | null;
  last_error: string | null;
  sent_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

export type AdminChannelsTabProps = {
  channels: AdminChannelRow[];
  channelSessions: AdminChannelSessionRow[];
  channelDeliveryTargets: AdminChannelDeliveryTargetRow[];
  channelDeliveryLogs: AdminChannelDeliveryLogRow[];
  setChannelDeliveryTargets: Dispatch<
    SetStateAction<AdminChannelDeliveryTargetRow[]>
  >;
  channelDeliveryProjectId: string;
  setChannelDeliveryProjectId: Dispatch<SetStateAction<string>>;
  channelDeliveryEventType: string;
  setChannelDeliveryEventType: Dispatch<SetStateAction<string>>;
  channelDeliveryChannelId: string;
  setChannelDeliveryChannelId: Dispatch<SetStateAction<string>>;
  channelDeliveryTarget: string;
  setChannelDeliveryTarget: Dispatch<SetStateAction<string>>;
  channelDeliveryLoading: boolean;
  setChannelDeliveryLoading: Dispatch<SetStateAction<boolean>>;
  channelDeliveryError: string | null;
  setChannelDeliveryError: Dispatch<SetStateAction<string | null>>;
  projects: ProjectOptionRow[];
  availableLoading: boolean;
  setAvailableLoading: Dispatch<SetStateAction<boolean>>;
  showAddChannel: boolean;
  setShowAddChannel: Dispatch<SetStateAction<boolean>>;
  availableChannels: AdminChannelRow[];
  setAvailableChannels: Dispatch<SetStateAction<AdminChannelRow[]>>;
  channelCatalogSearch: string;
  setChannelCatalogSearch: Dispatch<SetStateAction<string>>;
  filteredAvailableChannels: AdminChannelRow[];
  configuringChannel: AdminChannelRow | null;
  setConfiguringChannel: Dispatch<SetStateAction<AdminChannelRow | null>>;
  channelFormName: string;
  setChannelFormName: Dispatch<SetStateAction<string>>;
  channelFormProjectId: string;
  setChannelFormProjectId: Dispatch<SetStateAction<string>>;
  channelFormEnabled: boolean;
  setChannelFormEnabled: Dispatch<SetStateAction<boolean>>;
  channelConfigJson: string;
  setChannelConfigJson: Dispatch<SetStateAction<string>>;
  channelFormValues: Record<string, unknown>;
  setChannelFormValues: Dispatch<SetStateAction<Record<string, unknown>>>;
  channelShowRawJson: boolean;
  setChannelShowRawJson: Dispatch<SetStateAction<boolean>>;
  channelFormLoading: boolean;
  setChannelFormLoading: Dispatch<SetStateAction<boolean>>;
  channelFormError: string | null;
  setChannelFormError: Dispatch<SetStateAction<string | null>>;
  getChannelIconColor: (pluginId: string) => string;
  renderChannelIcon: (pluginId: string) => ReactNode;
  formatRelativeTime: (value: string | null | undefined) => string;
  readJson: ReadJsonFn;
  reloadChannelsTab: () => void;
};
