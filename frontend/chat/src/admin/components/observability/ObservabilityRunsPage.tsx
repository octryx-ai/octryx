import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { RunDrawer } from "./RunDrawer";
import { WorkflowRunsSection } from "./WorkflowRunsSection";
import { RunsTable, RunsToolbar } from "./ObservabilityRunsParts";
import type { ProjectOption } from "./obUi";
import { windowLabel } from "./runsModel";
import { useRunsPage } from "./useRunsPage";
import "./observability.css";

type Props = { projects: ProjectOption[]; readJson: ReadJsonFn };

// Observability → Runs: every run of every source in a bounded window, paged on the server.
export function ObservabilityRunsPage({ projects, readJson }: Props) {
  const state = useRunsPage(readJson);
  const { page, setPage, data, error, loading, openRun, setOpenRun } = state;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="ob-page" data-testid="observability-runs">
      <WorkflowRunsSection readJson={readJson} />
      <RunsToolbar state={state} projects={projects} />
      {error ? <div className="ob-warn" role="alert">{error}</div> : null}
      <RunsTable data={data} onOpen={setOpenRun} />
      <div className="ob-between">
        <span className="ob-muted">
          {data ? `${data.total} of ${data.total_in_window} runs in ${windowLabel(data.window_hours)}` : loading ? "Loading runs…" : ""}
        </span>
        <div className="ob-row">
          <span className="ob-muted">Page {page} of {pages}</span>
          <button type="button" className="admin-panel__action-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <button type="button" className="admin-panel__action-btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      </div>
      {openRun ? (
        <RunDrawer
          runKey={openRun.run_key}
          row={openRun}
          readJson={readJson}
          onClose={() => setOpenRun(null)}
        />
      ) : null}
    </div>
  );
}
