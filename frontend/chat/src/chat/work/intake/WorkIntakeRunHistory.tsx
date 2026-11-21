import { useEffect, useState } from "react";

import { formatDateTime } from "../workUtils";
import { readRun, runAutomationText, runCountsText, runOutcome, type IntakeRun } from "../workIntakeRunsModel";
import { loadIntakeRuns } from "./workIntakeApi";

// The last runs of one intake (§3.5), read from `…/intake/{id}/runs`: time, trigger, result and detail
// (the counts, or the failure code with the source's own message).
export function WorkIntakeRunHistory({ workspaceId, intakeId, reloadKey }: {
  workspaceId: string;
  intakeId: string;
  reloadKey?: string | number;
}) {
  const [runs, setRuns] = useState<IntakeRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setError(null);
    loadIntakeRuns(workspaceId, intakeId)
      .then((listed) => {
        if (active) setRuns(listed.map((run) => readRun(run)).filter((run): run is IntakeRun => run !== null));
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Could not load the run history.");
      });
    return () => {
      active = false;
    };
  }, [workspaceId, intakeId, reloadKey]);

  if (error) return <p className="admin-panel__hint" role="alert">{error}</p>;
  if (runs === null) return <p className="admin-panel__hint">Loading run history…</p>;
  if (!runs.length) return <p className="admin-panel__hint">No run recorded yet.</p>;
  return (
    <table className="admin-panel__table work-cards" data-testid="intake-runs">
      <thead><tr><th>Time</th><th>Trigger</th><th>Result</th><th>Detail</th></tr></thead>
      <tbody>
        {runs.map((run) => {
          const outcome = run.mode === "preview" && run.status === "completed"
            ? { label: "preview", tone: "neutral" as const, detail: null }
            : runOutcome(run);
          const detail = outcome.detail ?? runCountsText(run.summary);
          const automation = outcome.detail ? "" : runAutomationText(run.summary);
          return (
            <tr key={run.id} data-testid="intake-run">
              <td data-label="Time">{formatDateTime(run.at)}</td>
              <td data-label="Trigger">{run.trigger}</td>
              <td data-label="Result"><span className={`work-badge work-badge--${outcome.tone}`}>{outcome.label}</span></td>
              <td data-label="Detail">
                {detail || "–"}
                {automation ? <div className="work-intake__muted" data-testid="intake-run-automation">{automation}</div> : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
