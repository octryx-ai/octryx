import { useState } from "react";
import { formatExactTime, formatRelative } from "../../admin/utils/dateTime";
import { useConfirmAction } from "../../admin/components/confirm/useConfirmAction";
import { ActionMenu } from "../../admin/components/workflowSurfaces/ActionMenu";
import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { SegmentedTabs } from "../../layout/SegmentedTabs";
import {
  STATE_LABEL,
  STATE_TONE,
  allowanceBar,
  clientLabel,
  clientObjectName,
  modelLabel,
  presenceSummary,
  sensitivityBadge,
  showsAllowance,
} from "./agentPresenceModel";
import type { AllowanceBar, ConnectedClient } from "./agentPresenceModel";

// The "Connected clients" view (design system): one row per person and device, active ones by
// default ("Active now"); "All" adds the stopped ones. The allowance column appears only when the server returned
// allowance (admins/owners); nothing is estimated. A person's device can be removed from the list (⋯ menu,
// confirmed by name) where the server offers it (entries with an id).
export type ClientFilter = "active" | "all";

export function AgentsConnectedClients({ clients, now = Date.now(), onInstall, onRemove }: {
  clients: ConnectedClient[];
  now?: number;
  // Opens Install octryx-claude: the next step of an empty list.
  onInstall?: () => void;
  // Removes one person-and-device entry.
  onRemove?: (client: ConnectedClient) => Promise<void>;
}) {
  const [filter, setFilter] = useState<ClientFilter>("active");
  const { ask, dialog, notice } = useConfirmAction();
  const rows = clients;
  const withAllowance = showsAllowance(rows);
  if (!rows.length) {
    return (
      <div className="admin-panel__empty-state" data-testid="agents-clients-empty">
        <strong>{presenceSummary(rows)}</strong>
        <span>Start a session with octryx-claude in this Workspace to see it here.</span>
        {onInstall ? (
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={onInstall}>
            Install octryx-claude
          </button>
        ) : null}
      </div>
    );
  }
  const running = rows.filter((client) => client.state !== "stopped");
  const shown = filter === "active" ? running : rows;
  const askRemove = (client: ConnectedClient) => ask({
    title: `Remove ${clientObjectName(client)}?`,
    body: <p>The device leaves this list; it appears again when {client.user} starts a new session on it.</p>,
    confirmLabel: `Remove ${clientObjectName(client)}`,
    done: `${clientObjectName(client)} removed.`,
    run: async () => {
      try {
        await onRemove?.(client);
      } catch {
        throw new Error("The device could not be removed from the list.");
      }
    },
  });
  const columns: DataTableColumn<ConnectedClient>[] = [
    { key: "user", header: "User", render: (client) => <strong>{client.user}</strong> },
    { key: "client", header: "Client", render: (client) => (client.device ? `${client.device} · ${clientLabel(client)}` : clientLabel(client)) },
    { key: "state", header: "State", nowrap: true,
      render: (client) => <span className={`work-badge work-badge--${STATE_TONE[client.state]}`}>{STATE_LABEL[client.state]}</span> },
    { key: "work", header: "Work item", grow: true,
      render: (client) => (client.workItem ? <><strong>{client.workItem.key}</strong>{client.workItem.title ? <span>{client.workItem.title}</span> : null}</> : "—") },
    { key: "branch", header: "Branch", render: (client) => client.branch || "—" },
    { key: "model", header: "Model", render: (client) => modelLabel(client) },
    { key: "sensitive", header: "Sensitive data", render: (client) => <div data-testid="agents-sensitive"><SensitiveBadge client={client} /></div> },
    { key: "seen", header: "Last seen", nowrap: true,
      render: (client) => <span className="agents-clients__when" title={formatExactTime(client.lastSeenAt)}>{formatRelative(client.lastSeenAt, "—", now)}</span> },
  ];
  if (withAllowance) {
    columns.push({ key: "allowance", header: "Allowance", render: (client) => (
      <div data-testid="agents-allowance">
        {client.allowance ? (
          <>
            <Bar bar={allowanceBar("5h", client.allowance.fiveHourPct, client.allowance.fiveHourResetsAt, now)} />
            <Bar bar={allowanceBar("7d", client.allowance.sevenDayPct, client.allowance.sevenDayResetsAt, now)} />
          </>
        ) : "—"}
      </div>
    ) });
  }
  const removable = Boolean(onRemove);
  return (
    <>
      {notice}
      <div className="agents-clients__toolbar">
        <p className="agents-area__hint" data-testid="agents-clients-summary">{presenceSummary(rows)}</p>
        <SegmentedTabs label="Show clients" idPrefix="agents-clients" testId="agents-clients-filter" value={filter}
          onChange={(key) => setFilter(key === "all" ? "all" : "active")}
          tabs={[{ key: "active", label: "Active now", count: running.length }, { key: "all", label: "All", count: rows.length }]} />
      </div>
      {shown.length ? (
        <DataTable<ConnectedClient>
          label="Connected clients"
          testId="agents-clients-table"
          rows={shown}
          rowKey={(client) => client.id}
          columns={columns}
          rowMenu={removable ? (client) => (
            <ActionMenu row={{ objectName: clientObjectName(client) }}
              items={[{ label: "Remove…", danger: true, onSelect: () => askRemove(client) }]} />
          ) : undefined}
        />
      ) : <p className="admin-panel__empty-state" data-testid="agents-clients-none-active">No client is running right now. Choose All to see stopped sessions.</p>}
      {dialog}
    </>
  );
}

// Only detector names and counts, never the data; the badge clears when the user starts a new conversation.
function SensitiveBadge({ client }: { client: ConnectedClient }) {
  const badge = sensitivityBadge(client.sensitive);
  if (!badge) return <>—</>;
  return <span className="work-badge work-badge--running" title={badge.title}>{badge.label}</span>;
}

function Bar({ bar }: { bar: AllowanceBar | null }) {
  if (!bar) return null;
  return (
    <div className="agents-allowance" data-testid="agents-allowance-bar">
      <span className="agents-allowance__label">{bar.label} {bar.pct}%</span>
      <span className="agents-allowance__track" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={bar.width}
        aria-label={`${bar.label} allowance used`}>
        <span className={`agents-allowance__fill agents-allowance__fill--${bar.tone}`} style={{ width: `${bar.width}%` }} />
      </span>
      {bar.resets ? <span className="agents-allowance__reset">{bar.resets}</span> : null}
    </div>
  );
}
