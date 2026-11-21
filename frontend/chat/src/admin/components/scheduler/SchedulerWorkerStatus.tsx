import type { SchedulerStatusCheck } from "./useSchedulerStatusCheck";
import type { WorkerStatusView } from "./workerApplicationModel";
import { formatClock } from "../../utils/dateTime";

// Worker registration status of one scheduler row. Shown next to, not instead of,
// the configured active/paused switch.
export function SchedulerWorkerStatus({ view }: { view: WorkerStatusView }) {
  return (
    <div
      className={`admin-scheduler__worker admin-scheduler__worker--${view.tone}`}
    >
      <strong>{view.label}</strong>
      {view.nextRun ? <span> · Next run {view.nextRun}</span> : null}
      <div className="admin-scheduler__worker-detail">{view.detail}</div>
    </div>
  );
}

type SchedulerStatusCheckBarProps = {
  status: SchedulerStatusCheck;
  onCheck: () => void;
};

// The explicit "Check worker status" control: one request per click, no polling.
export function SchedulerStatusCheckBar({
  status,
  onCheck,
}: SchedulerStatusCheckBarProps) {
  return (
    <div className="admin-scheduler__check" aria-live="polite">
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onCheck}
        disabled={status.checking}
      >
        {status.checking ? "Checking…" : "Check worker status"}
      </button>
      {/* The as-of time only; what the status means is in the page help (help/admin/schedulers.md). */}
      {status.checkedAt ? (
        <span className="admin-panel__hint">
          Checked {formatClock(status.checkedAt)}
        </span>
      ) : null}
      {status.error ? (
        <div className="admin-panel__form-error">
          Worker status could not be checked: {status.error}. The list shows the
          last known status.
        </div>
      ) : null}
    </div>
  );
}
