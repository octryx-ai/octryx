import { DataTable } from "../../layout/DataTable";
import { StatusLabel, type StatusTone } from "../../layout/StatusLabel";
import type {
  AdminChannelDeliveryLogRow,
  AdminChannelRow,
  ProjectOptionRow,
} from "./channelTypes";
import "./adminChannels.css";

type AdminChannelDeliveryLogPanelProps = {
  logs: AdminChannelDeliveryLogRow[];
  channels: AdminChannelRow[];
  projects: ProjectOptionRow[];
  formatRelativeTime: (value: string | null | undefined) => string;
  onSetUpChannel: () => void;
};

// A delivery status in words with its one state colour; an unknown status reads as words.
const STATUS_LABELS: Record<string, { label: string; tone: StatusTone }> = {
  sent: { label: "Sent", tone: "neutral" },
  pending: { label: "Pending", tone: "info" },
  retrying: { label: "Retrying", tone: "info" },
  failed: { label: "Failed", tone: "problem" },
  dead_letter: { label: "Failed, no more retries", tone: "problem" },
};

export function deliveryStatus(status: string): { label: string; tone: StatusTone } {
  const known = STATUS_LABELS[status];
  if (known) return known;
  const words = status.replace(/_/g, " ").trim();
  return { label: words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unknown", tone: "neutral" };
}

function channelName(channels: AdminChannelRow[], channelId: number | null) {
  if (channelId == null) {
    return "Any active channel";
  }
  return (
    channels.find((channel) => channel.id === channelId)?.name ||
    `Channel ${channelId}`
  );
}

function projectName(
  projects: ProjectOptionRow[],
  log: AdminChannelDeliveryLogRow,
) {
  return (
    log.project_name ||
    projects.find((project) => project.id === log.project_id)?.name ||
    "No project"
  );
}

function shortTarget(target: string) {
  if (target.length <= 72) {
    return target;
  }
  return `${target.slice(0, 34)}...${target.slice(-28)}`;
}

export function AdminChannelDeliveryLogPanel({
  logs,
  channels,
  projects,
  formatRelativeTime,
  onSetUpChannel,
}: AdminChannelDeliveryLogPanelProps) {
  // No count cards and no section header; the messages as one compact table.
  return (
    <DataTable<AdminChannelDeliveryLogRow>
      label="Outbound messages"
      testId="channel-delivery-log"
      rows={logs}
      rowKey={(log) => log.id}
      empty={
        channels.length > 0
          ? { text: "No outbound channel messages yet." }
          : {
              text: "No channel is set up yet, so nothing can be sent.",
              action: { label: "Set up a channel", onClick: onSetUpChannel },
            }
      }
      columns={[
        {
          key: "status",
          header: "Status",
          nowrap: true,
          render: (log) => {
            const status = deliveryStatus(log.status);
            return <StatusLabel label={status.label} tone={status.tone} title={log.last_error || undefined} />;
          },
        },
        {
          key: "channel",
          header: "Channel",
          nowrap: true,
          render: (log) => `${channelName(channels, log.channel_config_id)} · ${log.channel_type}`,
        },
        { key: "project", header: "Workspace", nowrap: true, render: (log) => projectName(projects, log) },
        { key: "event", header: "Event", nowrap: true, render: (log) => log.event_type },
        {
          key: "target",
          header: "Target",
          grow: true,
          render: (log) => <span className="admin-channels__target-cell" title={log.target}>{shortTarget(log.target)}</span>,
        },
        { key: "retries", header: "Retries", nowrap: true, align: "end", render: (log) => log.retry_count },
        {
          key: "sent",
          header: "Sent",
          nowrap: true,
          render: (log) => formatRelativeTime(log.sent_at || log.created_at),
        },
        {
          key: "error",
          header: "Error",
          render: (log) => (log.last_error ? <span className="admin-channels__target-cell" title={log.last_error}>{log.last_error}</span> : ""),
        },
      ]}
    />
  );
}
