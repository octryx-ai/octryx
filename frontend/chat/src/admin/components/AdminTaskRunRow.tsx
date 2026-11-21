import { Fragment } from "react";
import { AdminTaskRunDetail } from "./AdminTaskRunDetail";
import { knownRunError } from "./actionRunError";
import { queueWaitReasonText } from "./queueWaitReason";
import type { PanelTaskRunRow } from "./taskTypes";
import { formatDateTime } from "../utils/dateTime";

type AdminTaskRunRowProps = {
  run: PanelTaskRunRow;
  taskId: string;
  expandedRun: string | null;
  setExpandedRun: (value: string | null) => void;
  statusColor: Record<string, string>;
  taskPaused?: boolean;
  cancellingRun: string | null;
  handleCancelRun: (taskId: string, runId: string) => Promise<void>;
};

function formatRunDuration(run: PanelTaskRunRow) {
  if (run.duration_seconds == null) {
    return run.status === "running" ? "running…" : "—";
  }
  if (run.duration_seconds >= 60) {
    return `${Math.floor(run.duration_seconds / 60)}m ${Math.round(run.duration_seconds % 60)}s`;
  }
  return `${run.duration_seconds.toFixed(1)}s`;
}

// The queue position the server reports. A wait estimate is shown only when it is
// positive; the stored default of 0 is not an estimate.
function formatQueue(run: PanelTaskRunRow) {
  if (run.queue_priority == null) return "—";
  const parts = [`p${run.queue_priority}`];
  if (run.status === "queued") {
    parts.push("waiting");
    const domain = run.queue_required_domain?.trim();
    if (domain && domain !== "any") parts.push(`needs a ${domain} worker`);
    const reason = queueWaitReasonText(run);
    if (reason) parts.push(reason);
  }
  if (
    typeof run.estimated_wait_seconds === "number" &&
    run.estimated_wait_seconds > 0
  ) {
    parts.push(`~${run.estimated_wait_seconds}s`);
  }
  return parts.join(" · ");
}

function formatRunStart(run: PanelTaskRunRow) {
  if (run.started_at) {
    return formatDateTime(run.started_at);
  }
  if (run.queued_at) {
    return `Queued ${formatDateTime(run.queued_at)}`;
  }
  return "—";
}

export function AdminTaskRunRow({
  run,
  taskId,
  expandedRun,
  setExpandedRun,
  statusColor,
  taskPaused = false,
  cancellingRun,
  handleCancelRun,
}: AdminTaskRunRowProps) {
  const isRunExpanded = expandedRun === run.id;
  const toggleRun = () => setExpandedRun(isRunExpanded ? null : run.id);
  const knownError = knownRunError(run);
  const detailId = `task-run-detail-${run.id}`;

  return (
    <Fragment>
      <tr
        className={`${run.status === "running" ? "task-run--active" : ""} task-run--clickable`}
        style={{ cursor: "pointer" }}
        onClick={toggleRun}
      >
        <td>
          <code className="task-run__id">{run.id.slice(0, 8)}</code>
          {run.session_id ? (
            <a
              href={`/chat?session_id=${run.session_id}`}
              target="_blank"
              rel="noopener noreferrer"
              className="task-run__session-link"
              title="Open chat"
              onClick={(event) => event.stopPropagation()}
            >
              ↗
            </a>
          ) : null}
        </td>
        <td>
          <span
            className="task-run__status"
            style={{ color: statusColor[run.status] || "var(--muted-strong)" }}
          >
            {run.status === "running" ? (
              <span className="task-run__spinner" />
            ) : null}
            {run.status}
          </span>
        </td>
        <td className="admin-panel__cell--muted">{formatQueue(run)}</td>
        <td className="admin-panel__cell--muted">{formatRunStart(run)}</td>
        <td className="admin-panel__cell--muted">{formatRunDuration(run)}</td>
        {/* A known refusal shows its cause; anything else the original text. */}
        <td
          className={`task-run__error${knownError ? " action-run-error__cell--known" : ""}`}
        >
          {knownError
            ? knownError.summary
            : run.error
              ? run.error.slice(0, 60)
              : "—"}
        </td>
        <td onClick={(event) => event.stopPropagation()}>
          {run.status === "running" || run.status === "queued" ? (
            <button
              type="button"
              className="admin-panel__danger-btn"
              style={{ fontSize: "var(--ds-text-xs)", padding: "0.2rem 0.5rem" }}
              disabled={cancellingRun === run.id}
              onClick={() => void handleCancelRun(taskId, run.id)}
            >
              {cancellingRun === run.id ? "…" : "Cancel"}
            </button>
          ) : null}
          {/* The cell stops propagation, so this toggles once; the row keeps its mouse toggle. */}
          <button
            type="button"
            className="admin-panel__icon-btn action-run-error__toggle"
            style={{ fontSize: "var(--ds-text-2xs)", marginLeft: "0.25rem" }}
            aria-expanded={isRunExpanded}
            aria-controls={isRunExpanded ? detailId : undefined}
            aria-label={isRunExpanded ? "Hide run details" : "Show run details"}
            title={isRunExpanded ? "Hide run details" : "Show run details"}
            onClick={toggleRun}
          >
            {isRunExpanded ? "▲" : "▼"}
          </button>
        </td>
      </tr>
      {isRunExpanded ? (
        <tr className="task-run__detail-row" id={detailId}>
          <AdminTaskRunDetail run={run} taskPaused={taskPaused} />
        </tr>
      ) : null}
    </Fragment>
  );
}
