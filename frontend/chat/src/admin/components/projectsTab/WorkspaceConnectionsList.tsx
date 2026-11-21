import { useCallback, useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { TimeText } from "../../utils/TimeText";
import { DataTable } from "../../../layout/DataTable";
import { EmptyLine } from "../../../layout/EmptyLine";
import { StatusLabel } from "../../../layout/StatusLabel";
import { listConnections, loadConnectionTypes, type ListResult } from "../connections/connectionsApi";
import { typeLabel, type ConnectionType } from "../connections/connectionTypes";
import { connectionAddress, stateWord, usesText, type ConnectionRow } from "../connections/connectionsModel";

export const WORKSPACE_CONNECTIONS_PENDING = "Connections arrive with the central configuration.";

// Workspace › Data › Connectors: the connections available in this Workspace, read-only, from
// the central connections API with the Workspace filter. They are set up and changed in Admin › Connections; a row
// opens the connection there. No second place to edit a connection.
export function WorkspaceConnectionsList({ workspaceId }: { workspaceId: string }) {
  const { openAdminTab } = useAdminNavigation();
  const [result, setResult] = useState<ListResult | null>(null);
  const [types, setTypes] = useState<ConnectionType[]>([]);

  const load = useCallback(async () => {
    setResult(null);
    setResult(await listConnections(workspaceId));
  }, [workspaceId]);
  useEffect(() => {
    let current = true;
    setResult(null);
    void listConnections(workspaceId).then((next) => { if (current) setResult(next); });
    void loadConnectionTypes().then((next) => { if (current) setTypes(next); });
    return () => { current = false; };
  }, [workspaceId]);

  const manage = () => openAdminTab("adminConnections");
  const openConnection = (row: ConnectionRow) => {
    if (typeof window !== "undefined" && window.history?.replaceState) {
      window.history.replaceState(window.history.state, "", `${window.location.pathname}${connectionAddress(window.location.search, row.id)}`);
    }
    manage();
  };

  return (
    <section className="workspace-data__section" aria-labelledby="workspace-connections-title" data-testid="workspace-connections">
      <div className="workspace-data__head">
        <h3 id="workspace-connections-title" className="workspace-data__title">Connections</h3>
        <button type="button" className="ds-link-button" onClick={manage} data-testid="workspace-connections-manage">
          Manage in Admin › Connections
        </button>
      </div>
      {result?.kind === "needs_configuration" ? (
        <EmptyLine text={WORKSPACE_CONNECTIONS_PENDING} testId="workspace-connections-pending" />
      ) : result?.kind === "error" ? (
        <EmptyLine text={result.message} action={{ label: "Try again", onClick: () => void load() }} testId="workspace-connections-error" />
      ) : (
        <DataTable<ConnectionRow>
          label="Connections"
          testId="workspace-connections-table"
          loading={result === null}
          rows={result?.kind === "ok" ? result.connections : []}
          rowKey={(row) => row.id}
          onOpen={openConnection}
          empty={{ text: "No connection is available in this Workspace.", action: { label: "Manage in Admin › Connections", onClick: manage } }}
          columns={[
            { key: "name", header: "Name", grow: true, minWidth: "12rem", render: (row) => row.name },
            { key: "type", header: "Type", nowrap: true, render: (row) => typeLabel(row.type, types) },
            { key: "state", header: "State", nowrap: true, render: (row) => {
              const word = stateWord(row.state);
              return <StatusLabel label={word.label} tone={word.tone} title={row.stateReason || undefined} />;
            } },
            { key: "uses", header: "Uses", nowrap: true, render: (row) => usesText(row.uses) },
            { key: "tested", header: "Last tested", nowrap: true, render: (row) => <TimeText value={row.lastTestedAt} mode="recent" fallback="Never" /> },
          ]}
        />
      )}
    </section>
  );
}
