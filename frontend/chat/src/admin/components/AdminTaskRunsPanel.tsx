import type { Dispatch, SetStateAction } from "react";
import { AdminTaskRunsTable } from "./AdminTaskRunsTable";
import type { PanelTaskRunRow } from "./taskTypes";
import { queueWaitReasonText } from "./queueWaitReason";
import { LoadingState } from "../../layout/LoadingState";

/** Why the run status may be stale, and how many runs wait in the queue (and whether the list says why). */
function TaskRunsNotes({ runsError, queued, unexplained }: { runsError: string | null; queued: number; unexplained: boolean }) {
  return (
    <>
      {runsError ? (
        <div className="admin-panel__form-error" role="alert">
          Run status could not be refreshed: {runsError}. The list shows the
          last known status.
        </div>
      ) : null}
      {queued ? (
        <div className="admin-panel__hint" data-testid="task-runs-queued-note">
          {queued === 1 ? "1 run is" : `${queued} runs are`} queued and not
          started yet. A queued run starts once the scheduler dispatches it;{" "}
          {unexplained
            ? "this list does not report why it is still waiting."
            : "each row says why it is still waiting."}{" "}
          Use Refresh to check again.
        </div>
      ) : null}
    </>
  );
}

type AdminTaskRunsPanelProps = {
  isExpanded: boolean;
  runCount: number;
  taskId: string;
  runsLoading: string | null;
  runsError?: string | null;
  runs: PanelTaskRunRow[];
  expandedRun: string | null;
  setExpandedRun: Dispatch<SetStateAction<string | null>>;
  statusColor: Record<string, string>;
  // The Action is paused; run-error guidance then starts with resuming it.
  taskPaused?: boolean;
  setTaskRuns: Dispatch<SetStateAction<Record<string, PanelTaskRunRow[]>>>;
  loadTaskRuns: (
    taskId: string,
    options?: { refresh?: boolean },
  ) => Promise<void>;
  cancellingRun: string | null;
  handleCancelRun: (taskId: string, runId: string) => Promise<void>;
};

export function AdminTaskRunsPanel({
  isExpanded, runCount, taskId, runsLoading, runsError = null, runs, expandedRun, setExpandedRun, statusColor, taskPaused = false,
  setTaskRuns, loadTaskRuns, cancellingRun, handleCancelRun,
}: AdminTaskRunsPanelProps) {
  if (!isExpanded) {
    return null;
  }
  const refreshing = runsLoading === taskId;
  const queuedRuns = runs.filter((run) => run.status === "queued");
  const queued = queuedRuns.length;
  // Say "not reported" only while some queued run has no known waiting reason.
  const unexplained = queuedRuns.some((run) => !queueWaitReasonText(run));

  return (
    <div className="task-item__runs">
      <div className="task-item__runs-header">
        <span>Execution History ({runCount})</span>
        <button
          type="button"
          className="admin-panel__action-btn"
          disabled={refreshing}
          onClick={() => void loadTaskRuns(taskId, { refresh: true })}
        >
          {refreshing && runs.length ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <TaskRunsNotes runsError={runsError} queued={queued} unexplained={unexplained} />

      {refreshing && !runs.length ? (
        <LoadingState label="runs" />
      ) : runs.length === 0 ? (
        <div
          className="admin-panel__cell--muted"
          style={{ padding: "0.75rem", fontSize: "var(--ds-text-sm)" }}
        >
          No executions yet.
        </div>
      ) : (
        <AdminTaskRunsTable
          taskId={taskId}
          runs={runs}
          expandedRun={expandedRun}
          setExpandedRun={setExpandedRun}
          statusColor={statusColor}
          taskPaused={taskPaused}
          cancellingRun={cancellingRun}
          handleCancelRun={handleCancelRun}
        />
      )}
    </div>
  );
}
