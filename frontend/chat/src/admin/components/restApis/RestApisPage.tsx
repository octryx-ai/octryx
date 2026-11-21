import { useCallback, useEffect, useState } from "react";

import { DataTable } from "../../../layout/DataTable";
import { StatusLabel } from "../../../layout/StatusLabel";
import { AdminHeaderActions } from "../AdminHeaderSlot";
import { RestApiAddPanel } from "./RestApiAddPanel";
import { RestApiDetailPanel } from "./RestApiDetailPanel";
import { listDefinitions } from "./restApisApi";
import { definitionRow, type DefinitionRow } from "./restOperationsModel";
import { restErrorView } from "./restErrorsModel";
import { FormError, Mono } from "./restApisParts";
import "./restApis.css";

export type Workspace = { id: string; name: string };

const countText = (value: number, one: string, many: string) => (value === 1 ? `1 ${one}` : `${value} ${many}`);

// Admin › Connections › REST APIs (backend): every REST API an admin added, with how many operations are on,
// its connections and its warnings. A row opens the API in a side panel; "Add REST API" imports or enters one.
export function RestApisPage({ projects }: { projects: Workspace[] }) {
  const [rows, setRows] = useState<DefinitionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  // One request: the list carries the operation, connection and warning counts (backend).
  const load = useCallback(async () => {
    try {
      setRows((await listDefinitions()).map(definitionRow));
      setError(null);
    } catch (failure) {
      setRows([]);
      setError(restErrorView(failure).text);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const openAdd = () => { setOpenId(null); setAdding(true); };

  return (
    <div className="rst-page" data-testid="rest-apis-page">
      <AdminHeaderActions>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={openAdd}
          data-testid="rest-add">
          Add REST API
        </button>
      </AdminHeaderActions>
      <FormError text={error} />
      <DataTable<DefinitionRow>
        label="REST APIs"
        testId="rest-api-table"
        rows={rows ?? []}
        loading={rows === null}
        loadingLabel="REST APIs"
        rowKey={(row) => row.id}
        selectedKey={openId}
        onOpen={(row) => { setAdding(false); setOpenId(row.id); }}
        empty={{
          text: "Add a REST API: import its OpenAPI description or enter it by hand.",
          action: { label: "Add REST API", onClick: openAdd },
          testId: "rest-empty",
        }}
        columns={[
          {
            key: "name", header: "Name", grow: true, minWidth: "12rem",
            render: (row) => <span className="rst-name"><span className="rst-name__main">{row.name}</span></span>,
          },
          { key: "key", header: "Key", nowrap: true, render: (row) => <Mono>{row.key}</Mono> },
          { key: "source", header: "Source", nowrap: true, render: (row) => row.source },
          {
            key: "operations", header: "Operations on", nowrap: true, align: "end",
            render: (row) => `${row.enabled} of ${row.total}`,
          },
          {
            key: "connections", header: "Connections", nowrap: true, align: "end",
            render: (row) => (row.connections ? String(row.connections) : <span className="rst-muted">None</span>),
          },
          {
            key: "warnings", header: "Warnings", nowrap: true,
            render: (row) => (row.warnings ? <StatusLabel label={countText(row.warnings, "warning", "warnings")} tone="attention" />
              : <span className="rst-muted">None</span>),
          },
        ]}
      />
      {adding ? (
        <RestApiAddPanel onClose={() => setAdding(false)}
          onOpen={(id) => { setAdding(false); setOpenId(id); void load(); }} />
      ) : null}
      {openId ? (
        <RestApiDetailPanel definitionId={openId} workspaces={projects}
          onClose={() => { setOpenId(null); void load(); }}
          onDeleted={() => { setOpenId(null); void load(); }} />
      ) : null}
    </div>
  );
}
