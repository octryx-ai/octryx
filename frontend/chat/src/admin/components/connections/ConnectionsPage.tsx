import { useCallback, useEffect, useMemo, useState } from "react";

import { TimeText } from "../../utils/TimeText";
import { useAdminNavigation } from "../../adminNavigation";
import { AdminHeaderActions } from "../AdminHeaderSlot";
import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { StatusLabel } from "../../../layout/StatusLabel";
import { AddConnectionPanel } from "./AddConnectionPanel";
import { ConnectionDetailPanel } from "./ConnectionDetailPanel";
import { listConnections, loadConnectionTypes, type ListResult } from "./connectionsApi";
import { typeLabel, type ConnectionType } from "./connectionTypes";
import {
  availableInText,
  connectionAddress,
  connectorSettingsAddress,
  readConnectionAddress,
  stateWord,
  usesText,
  type ConnectionRow,
  type ConnectionState,
  type WorkspaceRef,
} from "./connectionsModel";
import "./connections.css";

// Admin › Connections: every connection once, with where it is
// available, what it is used for, how many workspaces narrow it, and its state. A row opens it in the side panel
// (?connection=<id>, "Open as page" adds connection_view=page). When the server keeps no central connections (404),
// the page says so in one line and links the setup pages; it never shows stand-in data. "Connector settings" (header,
// and a connection's ⋯ menu for its type) opens the page for built-in connector setup and private hosts.

export const CONNECTIONS_PENDING = "Connections arrive with the central configuration.";

const STATE_FILTERS: Array<{ key: "all" | ConnectionState; label: string }> = [
  { key: "all", label: "All" }, { key: "failing", label: "Failing" }, { key: "untested", label: "Not tested" },
  { key: "ok", label: "Working" }, { key: "disabled", label: "Off" },
];

function readAddress() {
  return typeof window === "undefined" ? { id: "", page: false } : readConnectionAddress(window.location.search);
}

function openConnectorSettingsAddress(type: string) {
  if (typeof window === "undefined" || !window.history?.replaceState) return;
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${connectorSettingsAddress(window.location.search, type)}`);
}

// The connection opened as its own page (connection_view=page) at the current address.
function connectionPageHref(id: string) {
  return `${typeof window === "undefined" ? "" : window.location.pathname}${connectionAddress(typeof window === "undefined" ? "" : window.location.search, id, true)}`;
}

function writeAddress(id: string, page = false) {
  if (typeof window === "undefined" || !window.history?.replaceState) return;
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${connectionAddress(window.location.search, id, page)}`);
}

// The page's list, filters, open connection and connection types, loaded on mount.
function useConnectionsState() {
  const [result, setResult] = useState<ListResult | null>(null);
  const [stateFilter, setStateFilter] = useState<"all" | ConnectionState>("all");
  const [typeFilter, setTypeFilter] = useState("");
  const [open, setOpen] = useState(readAddress);
  const [adding, setAdding] = useState(false);
  const [connectionTypes, setConnectionTypes] = useState<ConnectionType[]>([]);

  const load = useCallback(async () => setResult(await listConnections()), []);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    let current = true;
    void loadConnectionTypes().then((next) => { if (current) setConnectionTypes(next); });
    return () => { current = false; };
  }, []);
  return { result, stateFilter, setStateFilter, typeFilter, setTypeFilter, open, setOpen, adding, setAdding, connectionTypes, load };
}

function connectionColumns(connectionTypes: ConnectionType[]): DataTableColumn<ConnectionRow>[] {
  return [
    { key: "name", header: "Name", grow: true, render: (row) => (
      <>{row.name}{row.canEdit ? null : <span className="connections__readonly" title="Managed by the platform"> · read only</span>}</>
    ) },
    { key: "type", header: "Type", nowrap: true, render: (row) => typeLabel(row.type, connectionTypes) },
    { key: "state", header: "State", nowrap: true, render: (row) => {
      const word = stateWord(row.state);
      return <StatusLabel label={word.label} tone={word.tone} title={row.stateReason || undefined} />;
    } },
    { key: "available", header: "Available in", nowrap: true, render: (row) => availableInText(row.availableIn, row.workspaces) },
    { key: "uses", header: "Uses", nowrap: true, render: (row) => usesText(row.uses) },
    { key: "deviations", header: "Deviations", nowrap: true, align: "end", render: (row) => (row.deviationCount ? String(row.deviationCount) : "—") },
    { key: "tested", header: "Last tested", nowrap: true, render: (row) => <TimeText value={row.lastTestedAt} mode="recent" fallback="Never" /> },
  ];
}

function ConnectionsPending({ onOpenConnectors }: { onOpenConnectors: () => void }) {
  return (
    <section className="connections" data-testid="connections-pending">
      <EmptyLine text={CONNECTIONS_PENDING} testId="connections-pending-line" />
      <p className="connections__links">
        <span>Today in:</span>
        <button type="button" className="ds-link-button" onClick={onOpenConnectors}>Connectors</button>
        <a href="/chat?area=coding&coding_view=repositories&return_to=admin-connections">Repositories</a>
        <a href="/chat?area=work&work_view=writeback&return_to=admin-connections">Jira write-back</a>
      </p>
    </section>
  );
}

type ConnectionsFiltersProps = {
  stateFilter: "all" | ConnectionState;
  setStateFilter: (filter: "all" | ConnectionState) => void;
  typeFilter: string;
  setTypeFilter: (type: string) => void;
  types: string[];
  connectionTypes: ConnectionType[];
  counts: (key: "all" | ConnectionState) => number;
};

function ConnectionsFilters({ stateFilter, setStateFilter, typeFilter, setTypeFilter, types, connectionTypes, counts }: ConnectionsFiltersProps) {
  return (
    <div className="connections__filters">
      <SegmentedTabs label="State" size="small" idPrefix="connections-state" value={stateFilter} testId="connections-state-filter"
        tabs={STATE_FILTERS.map((filter) => ({ key: filter.key, label: filter.label, count: counts(filter.key) }))}
        onChange={(key) => setStateFilter(key as "all" | ConnectionState)} />
      {types.length > 1 ? (
        <select className="admin-panel__input connections__type-filter" aria-label="Type" value={typeFilter}
          onChange={(event) => setTypeFilter(event.target.value)} data-testid="connections-type-filter">
          <option value="">All types</option>
          {types.map((type) => <option key={type} value={type}>{typeLabel(type, connectionTypes)}</option>)}
        </select>
      ) : null}
    </div>
  );
}

function ConnectionsHeaderActions({ onConnectorSettings, onAdd }: { onConnectorSettings: () => void; onAdd: () => void }) {
  return (
    <AdminHeaderActions>
      <button type="button" className="admin-panel__action-btn" onClick={onConnectorSettings}
        data-testid="connections-connector-settings">Connector settings</button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={onAdd}
        data-testid="connections-add">Add connection</button>
    </AdminHeaderActions>
  );
}

export function ConnectionsPage({ projects, isAdmin = false }: { projects: WorkspaceRef[]; isAdmin?: boolean }) {
  const { openAdminTab } = useAdminNavigation();
  const {
    result, stateFilter, setStateFilter, typeFilter, setTypeFilter, open, setOpen, adding, setAdding, connectionTypes, load,
  } = useConnectionsState();

  const select = (id: string, page = false) => {
    setOpen({ id, page });
    writeAddress(id, page);
  };
  const openConnectorSettings = (type = "") => {
    openConnectorSettingsAddress(type);
    openAdminTab("connectors");
  };

  const rows = useMemo(() => (result?.kind === "ok" ? result.connections : []), [result]);
  const types = useMemo(() => Array.from(new Set(rows.map((row) => row.type))).sort(), [rows]);
  const shown = rows.filter((row) => (stateFilter === "all" || row.state === stateFilter) && (!typeFilter || row.type === typeFilter));
  const counts = (key: "all" | ConnectionState) => rows.filter((row) => key === "all" || row.state === key).length;

  if (result?.kind === "needs_configuration") return <ConnectionsPending onOpenConnectors={() => openAdminTab("connectors")} />;

  const detail = open.id ? (
    <ConnectionDetailPanel id={open.id} workspaces={projects} types={connectionTypes} mode={open.page ? "page" : "panel"}
      pageHref={connectionPageHref(open.id)} onClose={() => select("")} onChanged={() => void load()}
      onDeleted={() => select("")} onOpenConnectorSettings={openConnectorSettings} isAdmin={isAdmin} />
  ) : null;
  if (open.id && open.page) return <section className="connections" data-testid="connections-page">{detail}</section>;

  return (
    <section className="connections" data-testid="connections-page">
      <ConnectionsHeaderActions onConnectorSettings={() => openConnectorSettings()} onAdd={() => setAdding(true)} />
      {result?.kind === "error" ? (
        <EmptyLine text={result.message} action={{ label: "Try again", onClick: () => void load() }} testId="connections-error" />
      ) : (
        <>
          <ConnectionsFilters stateFilter={stateFilter} setStateFilter={setStateFilter} typeFilter={typeFilter} setTypeFilter={setTypeFilter}
            types={types} connectionTypes={connectionTypes} counts={counts} />
          <DataTable<ConnectionRow>
            label="Connections" testId="connections-table" loading={result === null}
            rows={shown} rowKey={(row) => row.id} selectedKey={open.id || null} onOpen={(row) => select(row.id)}
            empty={rows.length ? { text: "No connection matches this filter." }
              : { text: "No connection yet.", action: { label: "Add connection", onClick: () => setAdding(true) } }}
            columns={connectionColumns(connectionTypes)}
          />
        </>
      )}
      {detail}
      {adding ? (
        <AddConnectionPanel types={connectionTypes} workspaces={projects} onClose={() => setAdding(false)} onCreated={(created) => {
          setAdding(false);
          void load();
          if (created) select(created.id);
        }} />
      ) : null}
    </section>
  );
}
