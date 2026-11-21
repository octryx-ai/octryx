// Workflows → Check results: the latest checked turns across runtimes.
import { useCallback, useEffect, useState } from "react";

import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import { Badge } from "../awBadges";
import {
  CHECK_RESULTS_PATH,
  checkStateLabel,
  failedCheckLabel,
  readCheckResults,
  runtimeLabel,
  type CheckResultRow,
} from "./workflowsModel";
import { formatDateTime } from "../../../utils/dateTime";

const RESULTS_LIMIT = 100;

function stateKind(state: string): "active" | "attention" | "danger" {
  if (state === "passed") return "active";
  return state === "stop_blocked" ? "danger" : "attention";
}

export function CheckResultsTable({ readJson }: { readJson: ReadJsonFn }) {
  const [rows, setRows] = useState<CheckResultRow[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(readCheckResults(await readJson<unknown>(`${CHECK_RESULTS_PATH}?limit=${RESULTS_LIMIT}`)));
      setProblem(null);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The check results could not be loaded.");
    }
  }, [readJson]);
  useEffect(() => { void load(); }, [load]);

  return (
    <>
      <p className="admin-panel__hint">
        Checks run at the end of every turn that used a workflow, in platform chat and in octryx-claude&apos;s Stop
        hook. Blocking checks hold the turn (chat: one repair attempt, then &quot;Not verified&quot;; octryx-claude:
        Stop blocked with the reason).
      </p>
      {problem ? <p className="admin-panel__error" role="alert">{problem}</p> : null}
      {!rows && !problem ? <p className="admin-panel__hint" role="status">Loading check results…</p> : null}
      {rows && rows.length === 0 ? (
        <div className="admin-panel__empty-state">No turn has run a workflow with checks yet.</div>
      ) : null}
      {rows && rows.length ? (
        <table className="admin-panel__table aw-cards aw-table" data-testid="check-results">
          <thead>
            <tr><th>When</th><th>Session</th><th>Workflow</th><th>Runtime</th><th>Result</th><th>Failed check</th></tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td data-l="When">{row.createdAt ? formatDateTime(row.createdAt) : "–"}</td>
                <td data-l="Session"><span className="aw-mono">{row.sessionId ? row.sessionId.slice(0, 8) : "–"}</span></td>
                <td data-l="Workflow"><span className="aw-mono">{row.workflowKey}</span></td>
                <td data-l="Runtime">{runtimeLabel(row.runtime)}</td>
                <td data-l="Result"><Badge kind={stateKind(row.state)}>{checkStateLabel(row.state)}</Badge></td>
                <td data-l="Failed check">{failedCheckLabel(row) || "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </>
  );
}
