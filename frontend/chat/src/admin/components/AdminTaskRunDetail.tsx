import { AdminTaskRunStepItem } from "./AdminTaskRunStepItem";
import { knownRunError } from "./actionRunError";
import "./actionRunError.css";
import type { PanelTaskRunRow } from "./taskTypes";

type AdminTaskRunDetailProps = {
  run: PanelTaskRunRow;
  // The Action is paused, so the guidance says to resume it first.
  taskPaused?: boolean;
};

// A known refusal explains its cause and what to check; the original error stays available
// for support under "Technical details". Any other error is shown as its original text, unexplained.
function RunError({ run, taskPaused = false }: AdminTaskRunDetailProps) {
  if (!run.error) return null;
  const known = knownRunError(run, { paused: taskPaused });
  if (!known) {
    return (
      <div className="action-run-error" data-testid="action-run-error">
        <div className="action-run-error__summary">
          Error reported by the run
        </div>
        <pre className="action-run-error__raw">{run.error}</pre>
      </div>
    );
  }
  return (
    <div className="action-run-error" data-testid="action-run-error">
      <div className="action-run-error__summary">{known.summary}</div>
      <p className="action-run-error__guidance">{known.guidance}</p>
      <details className="action-run-error__technical">
        <summary>Technical details</summary>
        <pre className="action-run-error__raw">{run.error}</pre>
      </details>
    </div>
  );
}

export function AdminTaskRunDetail({
  run,
  taskPaused = false,
}: AdminTaskRunDetailProps) {
  return (
    // Themed surface (actionRunError.css); the old undefined-token light fallback made the
    // guidance illegible in the dark theme.
    <td colSpan={7} className="action-run-detail">
      <RunError run={run} taskPaused={taskPaused} />
      {run.steps_log && run.steps_log.length > 0 ? (
        <div>
          <div
            style={{
              fontSize: "var(--ds-text-2xs)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: "var(--muted)",
              marginBottom: "0.4rem",
            }}
          >
            Execution Pipeline
          </div>
          <div
            style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}
          >
            {run.steps_log.map((step) => (
              <AdminTaskRunStepItem key={step.step_id} step={step} />
            ))}
          </div>
        </div>
      ) : (
        <div style={{ fontSize: "var(--ds-text-xs)", color: "var(--muted)" }}>
          No step data recorded for this run.
        </div>
      )}
    </td>
  );
}
