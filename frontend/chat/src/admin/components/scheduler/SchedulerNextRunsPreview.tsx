import {
  formatRunTime,
  type SchedulePreviewState,
  type ScheduleSubmitGate,
} from "./scheduleModel";

type SchedulerNextRunsPreviewProps = {
  preview: SchedulePreviewState;
  gate: ScheduleSubmitGate;
  onRetry: () => void;
};

// Calculated next fire times for the expression in the form. These are the
// scheduler engine's own calculations, not observed runs.
export function SchedulerNextRunsPreview({
  preview,
  gate,
  onRetry,
}: SchedulerNextRunsPreviewProps) {
  return (
    <div
      className="task-form__field task-form__field--full admin-scheduler__preview"
      aria-live="polite"
    >
      <div className="admin-panel__form-label">Next runs</div>
      {preview.status === "idle" ? (
        <div className="admin-form-help">
          Enter a schedule to see when it runs.
        </div>
      ) : null}
      {preview.status === "loading" ? (
        <div className="admin-form-help">Calculating next runs…</div>
      ) : null}
      {preview.status === "failed" ? (
        <div className="admin-panel__form-error">
          The next runs could not be calculated: {preview.error}{" "}
          <button
            type="button"
            className="admin-panel__action-btn admin-scheduler__compact-btn"
            onClick={onRetry}
          >
            Retry
          </button>
        </div>
      ) : null}
      {preview.status === "ready" ? (
        <>
          {preview.result.valid ? (
            <ol className="admin-scheduler__runs">
              {preview.result.next_runs.map((run) => (
                <li key={run.at_utc}>
                  {formatRunTime(run.local)}
                  {run.dst_gap ? (
                    <span className="admin-scheduler__run-note">
                      {" "}
                      — clocks go forward: the set time does not exist that day,
                      so it runs at this time
                    </span>
                  ) : null}
                  {run.dst_repeat ? (
                    <span className="admin-scheduler__run-note">
                      {" "}
                      — clocks go back: this time occurs twice, and it runs
                      again
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
          ) : (
            <div className="admin-panel__form-error">
              {preview.result.error?.message}
            </div>
          )}
          {preview.result.warning ? (
            <div className="admin-scheduler__warning">
              {preview.result.warning.message}
            </div>
          ) : null}
          <div className="admin-form-help">
            Times use the time zone{" "}
            <strong>{preview.result.timezone.name}</strong> of this server
            process. {preview.result.scheduling.message}
          </div>
        </>
      ) : null}
      {gate.notice ? (
        <div className="admin-scheduler__warning">{gate.notice}</div>
      ) : null}
    </div>
  );
}
