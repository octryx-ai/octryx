import { buildChatSearch } from "../../chat/appHelpers";
import { DataTable } from "../../layout/DataTable";
import { StatusLabel } from "../../layout/StatusLabel";
import type { AdminChannelSessionRow } from "./channelTypes";
import "./adminChannels.css";

type AdminChannelSessionsTableProps = {
  sessions: AdminChannelSessionRow[];
  formatRelativeTime: (value: string | null | undefined) => string;
  hasChannels: boolean;
  onSetUpChannel: () => void;
};

function sessionLabel(session: AdminChannelSessionRow) {
  return session.channel_name || session.channel || "Channel";
}

function statusWords(status: string) {
  const words = status.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unknown";
}

// The channel sessions as one compact table; "Open" goes to the session's conversation.
export function AdminChannelSessionsTable({
  sessions,
  formatRelativeTime,
  hasChannels,
  onSetUpChannel,
}: AdminChannelSessionsTableProps) {
  return (
    <DataTable<AdminChannelSessionRow>
      label="Channel sessions"
      testId="channel-sessions-table"
      rows={sessions}
      rowKey={(session) => session.id}
      empty={
        hasChannels
          ? { text: "No channel sessions yet." }
          : {
              text: "No channel is set up yet, so no external conversations can start.",
              action: { label: "Set up a channel", onClick: onSetUpChannel },
            }
      }
      columns={[
        {
          key: "thread",
          header: "Thread",
          grow: true,
          render: (session) => <span title={session.conversation_id || undefined}>{session.title}</span>,
        },
        {
          key: "channel",
          header: "Channel",
          nowrap: true,
          render: (session) =>
            session.channel_type ? `${sessionLabel(session)} · ${session.channel_type}` : sessionLabel(session),
        },
        { key: "project", header: "Workspace", nowrap: true, render: (session) => session.project_name || "No Workspace" },
        {
          key: "status",
          header: "State",
          nowrap: true,
          render: (session) => <StatusLabel label={statusWords(session.status)} tone="neutral" />,
        },
        { key: "messages", header: "Messages", nowrap: true, align: "end", render: (session) => session.message_count },
        {
          key: "activity",
          header: "Last activity",
          nowrap: true,
          render: (session) => formatRelativeTime(session.last_message_at || session.started_at),
        },
        {
          key: "open",
          header: "",
          nowrap: true,
          render: (session) => (
            <a className="ds-link-button" href={`/chat${buildChatSearch({ sessionId: session.id })}`}>
              Open
            </a>
          ),
        },
      ]}
    />
  );
}
