import { useCallback, useEffect, useState } from "react";

import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { AddDatabaseConnectorModal } from "../connectorsTab/AddDatabaseConnectorModal";
import { AddDatabaseToolModal } from "../connectorsTab/AddDatabaseToolModal";
import "../automation/automationPages.css";
import "../adminDetailFacts.css";
import "./databases.css";
import { AdminHeaderActions } from "../AdminHeaderSlot";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { databaseNeedsAttention, databaseState, type DatabaseCard, type RecentQuery } from "./databasePresenters";
import {
  DatabasePanelFooter,
  DatabaseSidePanel,
  DatabasesTable,
  RecentQueriesTable,
} from "./databasesTabParts";
import { removeDatabase, togglePauseDatabase } from "./databaseRequests";

type AdminDatabasesTabProps = { ctx: Record<string, unknown> };

// Admin › Connections › Databases: one full-width table of databases with the query
// tool count and a real health check; a row opens the database in the side panel; the recent queries by agents are a
// second table below. The safety rules and what the states mean are in the page help (help/admin/databases.md).
export function AdminDatabasesTab({ ctx }: AdminDatabasesTabProps) {
  const {
    databaseConnectors = [],
    expandedDatabaseConnector,
    handleExpandDatabaseConnector,
    handleDeleteDatabaseConnector,
    readJson,
    resetDatabaseConnectorForm,
    setDatabaseConnectorError,
    setDatabaseConnectors,
    setShowAddDatabaseConnector,
  } = ctx as Record<string, any>;
  const [queries, setQueries] = useState<RecentQuery[]>([]);
  const [filter, setFilter] = useState<"all" | "attention">("all");
  const [removing, setRemoving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadQueries = useCallback(() => loadRecentQueries(readJson, setQueries), [readJson]);
  useEffect(() => { void loadQueries(); }, [loadQueries]);

  const cards = databaseConnectors as DatabaseCard[];
  const attention = cards.filter(databaseNeedsAttention);
  const shown = filter === "attention" ? attention : cards;
  const open = cards.find((connector) => connector.id === expandedDatabaseConnector) ?? null;

  const openAdd = () => {
    setDatabaseConnectorError(null);
    resetDatabaseConnectorForm();
    setShowAddDatabaseConnector(true);
  };

  const togglePause = (connector: DatabaseCard) => togglePauseDatabase(connector, { readJson, setDatabaseConnectors, setBusy, setError });
  const remove = (connector: DatabaseCard) => removeDatabase(connector, { handleDeleteDatabaseConnector, setRemoving, setBusy, setError });
  const state = open ? databaseState(open) : null;

  return (
    <div className="databases-page">
      <DatabasesHeader filter={filter} setFilter={setFilter} total={cards.length} attention={attention.length} onAdd={openAdd} />
      <DatabasesTable cards={cards} shown={shown} openId={open?.id ?? null} onOpen={handleExpandDatabaseConnector}
        onAdd={openAdd} />

      <h2 className="databases-page__section">Recent queries</h2>
      <RecentQueriesTable queries={queries} />

      {open && state ? (
        <DatabaseSidePanel open={open} state={state} ctx={ctx} onClose={() => handleExpandDatabaseConnector(open)} footer={
          <DatabasePanelFooter open={open} busy={busy} error={error} removing={removing}
            onRemove={() => { setError(null); setRemoving(true); }} onTogglePause={() => void togglePause(open)} />
        } />
      ) : null}
      {open && removing ? <RemoveDatabaseConfirm name={open.name} busy={busy} error={error} onCancel={() => setRemoving(false)}
        onConfirm={() => void remove(open)} /> : null}
      <AddDatabaseConnectorModal ctx={ctx} />
      <AddDatabaseToolModal ctx={ctx} />
    </div>
  );
}

async function loadRecentQueries(readJson: (url: string) => Promise<any>, setQueries: (rows: RecentQuery[]) => void) {
  try {
    setQueries(await readJson("/admin/chat/api/panel/database-query-runs?limit=10"));
  } catch {
    setQueries([]);
  }
}

type Filter = "all" | "attention";

function DatabasesHeader({
  filter,
  setFilter,
  total,
  attention,
  onAdd,
}: {
  filter: Filter;
  setFilter: (filter: Filter) => void;
  total: number;
  attention: number;
  onAdd: () => void;
}) {
  return (
    <>
      <AdminHeaderActions>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={onAdd}
          data-testid="database-add">
          Add database
        </button>
      </AdminHeaderActions>
      <SegmentedTabs label="Filter" size="small" idPrefix="database-filter" testId="database-filter" value={filter}
        onChange={(key) => setFilter(key as Filter)}
        tabs={[{ key: "all", label: "All", count: total }, { key: "attention", label: "Needs attention", count: attention }]} />
    </>
  );
}

function RemoveDatabaseConfirm({
  name,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  name: string;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <ConfirmDialog title={`Remove ${name}?`} confirmLabel="Remove database" typeToConfirm={name}
      busy={busy} error={error} onCancel={onCancel} onConfirm={onConfirm}>
      <p>Its query tools disappear from every agent, the stored password is deleted and the removal is audited.</p>
    </ConfirmDialog>
  );
}
