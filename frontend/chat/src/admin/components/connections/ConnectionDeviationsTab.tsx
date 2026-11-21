import { useState } from "react";

import { TimeText } from "../../utils/TimeText";
import { DataTable } from "../../../layout/DataTable";
import { errorUseLabel, lastSuccessfulTest, splitErrors, type ErrorLine } from "./connectionErrors";
import { canResetDeviation, deviationText, type ConnectionDetail, type Deviation } from "./connectionsModel";

// Where workspaces narrow this connection (a deviation is only ever narrower), each with "Reset", and the
// connection's recent errors (from health checks, syncs and intakes). Reset is offered to platform admins and to a
// workspace's own admin for that workspace's deviation: the deviation's can_edit, else the connection's.

export function DeviationsTab({ detail, onReset }: {
  detail: ConnectionDetail; onReset: (deviation: Deviation) => Promise<boolean>;
}) {
  const [problem, setProblem] = useState("");
  const reset = async (deviation: Deviation) => {
    setProblem("");
    if (!(await onReset(deviation))) setProblem(`${deviation.workspace.name} could not be reset.`);
  };
  return (
    <div className="connections__tab" data-testid="connection-tab-deviations">
      {problem ? <p className="connections__field-error" role="alert">{problem}</p> : null}
      <DataTable<Deviation>
        label="Deviations" testId="connection-deviations" rows={detail.deviations} rowKey={(deviation) => deviation.workspace.id}
        empty={{ text: "Every workspace uses this connection as it is." }}
        columns={[
          { key: "workspace", header: "Workspace", render: (deviation) => deviation.workspace.name },
          { key: "fields", header: "Narrows", grow: true, render: (deviation) => deviationText(deviation.fields) },
          { key: "reset", header: "", nowrap: true, align: "end", render: (deviation) => (!canResetDeviation(detail, deviation) ? null : (
            <button type="button" className="admin-panel__action-btn" onClick={() => void reset(deviation)}
              data-testid={`deviation-reset-${deviation.workspace.id}`}>Reset</button>
          )) },
        ]}
      />
    </div>
  );
}

function ErrorTable({ rows, label, testId, empty }: { rows: ErrorLine[]; label: string; testId: string; empty: string }) {
  return (
    <DataTable<ErrorLine>
      label={label} testId={testId} rows={rows}
      rowKey={(error) => `${error.at ?? ""}:${error.use}:${error.code || error.sentence}`}
      empty={{ text: empty }}
      columns={[
        { key: "at", header: "When", nowrap: true, render: (error) => <TimeText value={error.at} mode="recent" /> },
        { key: "use", header: "Use", nowrap: true, render: (error) => errorUseLabel(error.use) },
        { key: "message", header: "Error", grow: true, render: (error) => (
          <span title={error.code || undefined} data-testid="connection-error-sentence">{error.sentence}</span>
        ) },
      ]}
    />
  );
}

/** Errors since the last successful test, one sentence each (code as tooltip); older ones under "Earlier". */
export function ErrorsTab({ detail }: { detail: ConnectionDetail }) {
  const success = lastSuccessfulTest(detail);
  const { recent, earlier } = splitErrors(detail.recentErrors, success);
  return (
    <div className="connections__tab" data-testid="connection-tab-errors">
      <h4 className="connections__subhead">{success ? "Since the last successful test" : "Recent errors"}</h4>
      <ErrorTable rows={recent} label="Recent errors" testId="connection-errors"
        empty={success ? "No errors since the last successful test." : "No recent errors."} />
      {earlier.length ? (
        <details className="connections__earlier" data-testid="connection-errors-earlier">
          <summary>Earlier ({earlier.length})</summary>
          <ErrorTable rows={earlier} label="Earlier errors" testId="connection-errors-earlier-table" empty="" />
        </details>
      ) : null}
    </div>
  );
}
