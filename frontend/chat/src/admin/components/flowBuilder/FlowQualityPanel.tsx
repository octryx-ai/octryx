import type { FlowQualitySummary } from "./flowRunTypes";

type FlowQualityPanelProps = {
  summary: FlowQualitySummary | null;
  busy: boolean;
  disabled: boolean;
  onRefresh: () => void;
  onEvaluate: () => void;
};

function statusClass(status?: string): string {
  if (status === "passed" || status === "completed") return "flow-builder__badge--ok";
  if (status === "failed") return "flow-builder__badge--danger";
  if (status === "warning" || status === "pending_review") return "flow-builder__badge--warning";
  return "flow-builder__badge--neutral";
}

export function FlowQualityPanel({
  summary,
  busy,
  disabled,
  onRefresh,
  onEvaluate,
}: FlowQualityPanelProps) {
  const warnings = summary?.warnings ?? [];
  const evaluationRuns = summary?.evaluation_runs ?? [];
  return (
    <section className="flow-builder__quality-panel">
      <div className="flow-builder__quality-header">
        <div>
          <span className="admin-panel__section-title">Quality</span>
          <p className="admin-panel__muted">Observed run facts and persisted evaluations.</p>
        </div>
        <div className="flow-builder__quality-actions">
          <button type="button" onClick={() => onRefresh()} disabled={busy || disabled}>
            Refresh
          </button>
          <button type="button" onClick={() => onEvaluate()} disabled={busy || disabled}>
            Evaluate
          </button>
        </div>
      </div>
      {summary ? (
        <>
          <div className="flow-builder__quality-metrics">
            <span className={`flow-builder__badge ${statusClass(summary.status)}`}>{summary.status}</span>
            <span>Score {summary.score}</span>
            <span>{summary.node_count} nodes</span>
            <span>{summary.evidence_count} evidence</span>
            <span>{summary.artifact_count} artifacts</span>
            <span>{summary.token_usage.total_tokens ?? 0} tokens</span>
          </div>
          {warnings.length ? (
            <div className="flow-builder__quality-warnings">
              {warnings.map((warning) => (
                <span key={warning.code}>{warning.message}</span>
              ))}
            </div>
          ) : null}
          <div className="flow-builder__quality-runs">
            <strong>Evaluations</strong>
            {evaluationRuns.length ? (
              evaluationRuns.map((run) => (
                <div key={run.id} className="flow-builder__quality-run">
                  <span className={`flow-builder__badge ${statusClass(run.status)}`}>{run.status}</span>
                  <span>{run.passed_count} passed</span>
                  <span>{run.failed_count} failed</span>
                  <span>{run.average_score ?? "n/a"}</span>
                </div>
              ))
            ) : (
              <span className="admin-panel__muted">No persisted evaluations for this run yet.</span>
            )}
          </div>
        </>
      ) : (
        <div className="flow-builder__trace-empty">Run a flow, then refresh quality facts.</div>
      )}
    </section>
  );
}
