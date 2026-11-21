import type { ReactNode } from "react";
import { DataTable } from "../../layout/DataTable";
import { StatusLabel } from "../../layout/StatusLabel";
import { ActionMenu } from "./workflowSurfaces/ActionMenu";
import type { AdminChannelRow } from "./channelTypes";
import "./adminDetailFacts.css";

type AdminChannelCardListProps = {
  channels: AdminChannelRow[];
  getChannelIconColor: (pluginId: string) => string;
  renderChannelIcon: (pluginId: string) => ReactNode;
  formatRelativeTime: (value: string | null | undefined) => string;
  onToggleEnabled: (
    channel: AdminChannelRow,
    enabled: boolean,
  ) => Promise<void>;
  onConfigure: (channel: AdminChannelRow) => void;
  onReload: (channel: AdminChannelRow) => Promise<void>;
  onRemove: (channel: AdminChannelRow) => Promise<void>;
  onAdd?: () => void;
  // A row opens the channel's side panel.
  onOpen?: (channel: AdminChannelRow) => void;
  selectedKey?: string | null;
};

export function channelKey(channel: AdminChannelRow): string {
  return channel.id != null ? String(channel.id) : `${channel.plugin_id}-${channel.name}`;
}

/** Enabled, Running or Off, from the configured switch and the worker state. */
export function channelState(channel: AdminChannelRow): string {
  if (!channel.enabled) return "Off";
  return channel.status === "running" ? "Running" : "Enabled";
}

// The configured channels as one compact table; details and the actions open in
// the side panel (AdminChannelsTab), the row ⋯ menu repeats them with Remove last.
export function AdminChannelCardList({
  channels,
  getChannelIconColor,
  renderChannelIcon,
  formatRelativeTime,
  onToggleEnabled,
  onConfigure,
  onReload,
  onRemove,
  onAdd,
  onOpen,
  selectedKey = null,
}: AdminChannelCardListProps) {
  return (
    <DataTable<AdminChannelRow>
      label="Channels"
      testId="channels-table"
      rows={channels}
      rowKey={channelKey}
      onOpen={onOpen}
      selectedKey={selectedKey}
      empty={{
        text: "No channels yet.",
        action: onAdd ? { label: "Add channel", onClick: onAdd } : undefined,
        testId: "channels-empty",
      }}
      columns={[
        {
          key: "name",
          header: "Name",
          grow: true,
          render: (channel) => (
            <span className="admin-detail-name">
              <span
                className="admin-detail-name__icon"
                style={{ color: getChannelIconColor(channel.plugin_id) }}
                aria-hidden="true"
              >
                {renderChannelIcon(channel.plugin_id)}
              </span>
              <span>{channel.name}</span>
            </span>
          ),
        },
        { key: "type", header: "Type", nowrap: true, render: (channel) => channel.plugin_id },
        { key: "workspace", header: "Workspace", nowrap: true, render: (channel) => channel.project_name || "No Workspace" },
        {
          key: "state",
          header: "State",
          nowrap: true,
          // A running channel is the normal state: neutral, not "in progress".
          render: (channel) => <StatusLabel label={channelState(channel)} tone="neutral" />,
        },
        {
          key: "updated",
          header: "Updated",
          nowrap: true,
          render: (channel) => (channel.updated_at ? formatRelativeTime(channel.updated_at) : "Never"),
        },
      ]}
      rowMenu={(channel) => (
        <ActionMenu
          row={{ objectName: channel.name }}
          items={[
            { label: "Configure", onSelect: () => onConfigure(channel) },
            {
              label: channel.enabled ? "Disable" : "Enable",
              onSelect: () => void onToggleEnabled(channel, !channel.enabled),
            },
            { label: "Reload", onSelect: () => void onReload(channel) },
            { label: "Remove…", danger: true, onSelect: () => void onRemove(channel) },
          ]}
        />
      )}
    />
  );
}
