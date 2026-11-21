// Parts of Admin › Connections › Databases: the two tables, the open database's side panel and its footer, and the
// pause and remove requests.
import type { ReactNode } from "react";

import { TimeText } from "../../utils/TimeText";
import { ManagedDatabaseConnectorCard } from "../connectorsTab/ManagedDatabaseConnectorCard";
import { AutomationIcon } from "../automation/AutomationIcon";
import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import {
  databaseIconKind,
  databaseState,
  databaseTypeLabel,
  queryBy,
  queryResult,
  type DatabaseCard,
  type RecentQuery,
} from "./databasePresenters";

const DATABASE_COLUMNS: DataTableColumn<DatabaseCard>[] = [
  { key: "name", header: "Name", grow: true, render: (connector) => (
    <span className="admin-detail-name">
      <AutomationIcon kind={databaseIconKind(connector.db_type)} small />
      {connector.name}
    </span>
  ) },
  { key: "type", header: "Type", nowrap: true, render: (connector) => databaseTypeLabel(connector.db_type) },
  { key: "tools", header: "Query tools", nowrap: true, align: "end", render: (connector) => String(connector.tool_count) },
  { key: "state", header: "State", nowrap: true, render: (connector) => {
    const row = databaseState(connector);
    return <StatusLabel label={row.label} tone={row.tone} title={row.title} />;
  } },
];

const QUERY_COLUMNS: DataTableColumn<RecentQuery>[] = [
  { key: "time", header: "Time", nowrap: true, render: (query) => <TimeText value={query.started_at} mode="recent" /> },
  { key: "tool", header: "Tool", nowrap: true, render: (query) => query.tool },
  { key: "database", header: "Database", nowrap: true, render: (query) => query.database },
  { key: "by", header: "By", nowrap: true, render: (query) => queryBy(query) || "—" },
  { key: "result", header: "Result", grow: true, render: (query) => {
    const result = queryResult(query);
    if (!result.failed) return result.text;
    return <><StatusLabel label="Failed" title={result.text || undefined} />{result.text ? ` ${result.text}` : null}</>;
  } },
];

export function DatabasePanelFooter({
  open,
  busy,
  error,
  removing,
  onRemove,
  onTogglePause,
}: {
  open: DatabaseCard;
  busy: boolean;
  error: string | null;
  removing: boolean;
  onRemove: () => void;
  onTogglePause: () => void;
}) {
  return (
    <>
      {/* Remove (destructive, confirmed by name) stands apart on the left; Pause/Resume is the panel's action. */}
      <button type="button" className="admin-panel__danger-btn databases-page__remove" disabled={busy}
        onClick={onRemove} data-testid="database-remove">
        Remove…
      </button>
      {error && !removing ? <span className="automation-tone--error" role="alert">{error}</span> : null}
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={onTogglePause}
        data-testid="database-pause">
        {open.is_active ? "Pause" : "Resume"}
      </button>
    </>
  );
}

export function DatabasesTable({
  cards,
  shown,
  openId,
  onOpen,
  onAdd,
}: {
  cards: DatabaseCard[];
  shown: DatabaseCard[];
  openId: string | null;
  onOpen: (connector: DatabaseCard) => void;
  onAdd: () => void;
}) {
  return (
    <DataTable<DatabaseCard>
      label="Databases"
      testId="database-grid"
      rows={shown}
      rowKey={(connector) => connector.id}
      selectedKey={openId}
      onOpen={(connector) => onOpen(connector)}
      empty={{
        text: cards.length ? "Nothing needs attention." : "No databases yet.",
        action: cards.length ? undefined : { label: "Add database", onClick: onAdd },
        testId: "database-empty",
      }}
      columns={DATABASE_COLUMNS}
    />
  );
}

export function RecentQueriesTable({ queries }: { queries: RecentQuery[] }) {
  return (
    <DataTable<RecentQuery>
      label="Recent queries by agents"
      testId="database-queries"
      rows={queries}
      rowKey={(query) => query.id}
      empty={{ text: "No queries by agents yet.", testId: "database-queries-empty" }}
      columns={QUERY_COLUMNS}
    />
  );
}

export function DatabaseSidePanel({
  open,
  state,
  ctx,
  onClose,
  footer,
}: {
  open: DatabaseCard;
  state: ReturnType<typeof databaseState>;
  ctx: Record<string, unknown>;
  onClose: () => void;
  footer: ReactNode;
}) {
  return (
    <SidePanel title={open.name} subtitle={databaseTypeLabel(open.db_type)} testId="database-panel"
      onClose={onClose}
      headerActions={<StatusLabel label={state.label} tone={state.tone} title={state.title} testId="database-state" />}
      footer={footer}>
      {state.title ? <p className="databases-page__fact">{state.title}</p> : null}
      <ManagedDatabaseConnectorCard connector={open} ctx={ctx} inDrawer />
    </SidePanel>
  );
}
