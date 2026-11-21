import { useEffect, useState } from "react";

import { TimeText } from "../../../admin/utils/TimeText";
import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { readJson } from "../../chatApiClient";
import { SeatCell } from "../../cost/SeatCell";
import { seatHeading } from "../../cost/seatEquivalent";
import type { RepositoryOverviewRow } from "./repositoryPresenter";
import {
  recentRepositoryRuns, repositoryRunsPath, runsCountText, runsErrorText, type RepositoryRun, type RepositoryRunRow,
} from "./repositoryRunsModel";

// A repository's latest workflow runs, read when the panel opens (never one request per row on page load). Each run
// links to its chat, where the run card holds its actions (as on Work › Runs).
export function RepositoryRunsPanel({ row, onClose }: { row: RepositoryOverviewRow; onClose: () => void }) {
  const recordId = row.recordId ?? "";
  const [runs, setRuns] = useState<RepositoryRun[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setRuns(null); setError("");
    void readJson<{ runs?: RepositoryRun[] }>(repositoryRunsPath(recordId))
      .then((payload) => { if (!cancelled) setRuns(Array.isArray(payload.runs) ? payload.runs : []); })
      .catch((failure: unknown) => {
        if (cancelled) return;
        setRuns([]); setError(runsErrorText(failure instanceof Error ? failure.message : ""));
      });
    return () => { cancelled = true; };
  }, [recordId, attempt]);

  const rows = runs ? recentRepositoryRuns(runs) : [];
  const columns: DataTableColumn<RepositoryRunRow>[] = [
    { key: "name", header: "Run", grow: true, minWidth: "12rem",
      render: (run) => (run.href ? <a className="repository-runs__link" href={run.href}>{run.name}</a> : <span>{run.name}</span>) },
    { key: "status", header: "Status", nowrap: true, render: (run) => <StatusLabel label={run.status} tone={run.tone} /> },
    { key: "branch", header: "Branch", nowrap: true, clip: "10rem",
      render: (run) => (run.branch ? <code className="repository-overview__branch" title={run.branch}>{run.branch}</code> : "–") },
    { key: "when", header: "Started", nowrap: true, render: (run) => <TimeText value={run.when} mode="recent" fallback="–" /> },
    { key: "cost", header: "API cost", nowrap: true, align: "end", render: (run) => run.cost },
    { key: "seat", header: seatHeading(), nowrap: true, align: "end", render: (run) => <SeatCell figures={run.seat} empty="–" /> },
  ];
  const subtitle = [row.origin, row.branch].filter(Boolean).join(" · ");
  const count = runs ? runsCountText(runs.length, rows.length) : "";

  return <SidePanel title={`Runs of ${row.name}`} subtitle={subtitle} onClose={onClose} testId="repository-runs">
    <div className="repository-runs">
      {error ? <p role="alert" className="repository-list__error">{error}</p> : null}
      <DataTable label="Runs" columns={columns} rows={rows} rowKey={(run) => run.key} testId="repository-runs-table"
        loading={runs === null} loadingLabel="runs" onRetry={() => setAttempt((value) => value + 1)}
        empty={error ? { text: "No runs to show.", action: { label: "Try again", onClick: () => setAttempt((value) => value + 1) } }
          : { text: "No workflow run has used this repository yet." }} />
      {count ? <p className="repository-runs__count">{count}</p> : null}
    </div>
  </SidePanel>;
}
