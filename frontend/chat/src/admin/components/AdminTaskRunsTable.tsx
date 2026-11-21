import { AdminTaskRunRow } from "./AdminTaskRunRow";
import type { PanelTaskRunRow } from "./taskTypes";

type AdminTaskRunsTableProps = {
  taskId: string;
  runs: PanelTaskRunRow[];
  expandedRun: string | null;
  setExpandedRun: (value: string | null) => void;
  statusColor: Record<string, string>;
  taskPaused?: boolean;
  cancellingRun: string | null;
  handleCancelRun: (taskId: string, runId: string) => Promise<void>;
};

export function AdminTaskRunsTable({
  taskId,
  runs,
  expandedRun,
  setExpandedRun,
  statusColor,
  taskPaused = false,
  cancellingRun,
  handleCancelRun,
}: AdminTaskRunsTableProps) {
  return (
    <table className="admin-panel__table task-runs-table">
      <thead>
        <tr>
          <th>Execution ID</th>
          <th>Status</th>
          <th>Queue</th>
          <th>Started</th>
          <th>Duration</th>
          <th>Error</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <AdminTaskRunRow
            key={run.id}
            run={run}
            taskId={taskId}
            expandedRun={expandedRun}
            setExpandedRun={setExpandedRun}
            statusColor={statusColor}
            taskPaused={taskPaused}
            cancellingRun={cancellingRun}
            handleCancelRun={handleCancelRun}
          />
        ))}
      </tbody>
    </table>
  );
}
