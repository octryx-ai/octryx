import type { WorkCicdPipelineStageTrace, WorkCicdPipelineTrace } from "../work/workCicdTypes";

type PipelineTracePanelProps = {
  traces: WorkCicdPipelineTrace[];
  agentFailureContext: Record<string, unknown> | null;
};

export function CodingPipelineTracePanel({
  traces,
  agentFailureContext,
}: PipelineTracePanelProps) {
  if (traces.length === 0) {
    return (
      <section className="coding-detail__evidence" aria-label="CI/CD pipeline traces">
        <h3>Pipeline traces</h3>
        <p className="work-detail__empty">No CI/CD pipeline trace evidence captured yet.</p>
      </section>
    );
  }
  return (
    <div className="coding-detail__stack" role="region" aria-label="CI/CD pipeline traces">
      <section className="coding-detail__evidence">
        <h3>Pipeline traces</h3>
        <ul className="coding-pipeline-trace-list">
          {traces.map((trace) => (
            <li key={trace.id}>
              <PipelineTraceCard trace={trace} />
            </li>
          ))}
        </ul>
      </section>

      {agentFailureContext ? <TraceJson title="Agent failure context" value={agentFailureContext} /> : null}
    </div>
  );
}

function PipelineTraceCard({ trace }: { trace: WorkCicdPipelineTrace }) {
  return (
    <article className="coding-pipeline-trace">
      <header className="coding-pipeline-trace__header">
        <div>
          <strong>{trace.job_name}</strong>
          <small>
            {trace.provider_type} · build {trace.build_number || "-"} · {trace.branch_name || "branch unknown"}
          </small>
        </div>
        <span className={`work-badge work-badge--${traceTone(trace.status)}`}>{trace.status}</span>
      </header>
      <div className="coding-detail__metrics">
        <KeyValue label="Commit" value={trace.commit_sha || "-"} />
        <KeyValue label="PR" value={trace.pr_url || "-"} />
        <KeyValue label="Target" value={trace.deployment_target || "-"} />
        <KeyValue label="Failure" value={String(trace.failure_summary.primary_failure_type || "-")} />
      </div>
      <ol className="coding-process">
        {trace.stages.map((stage) => <PipelineStageItem key={`${trace.id}-${stage.stage_key}`} stage={stage} />)}
      </ol>
    </article>
  );
}

function PipelineStageItem({ stage }: { stage: WorkCicdPipelineStageTrace }) {
  return (
    <li className={`coding-process__stage is-${stage.status}`}>
      <details className="coding-pipeline-stage" open={stage.status === "failed" || stage.status === "unstable"}>
        <summary>
          <span>
            <strong>{stage.label}</strong>
            <small>
              {stage.stage_key} · {stage.failure_type || stage.result || stage.status}
            </small>
          </span>
          <span className={`work-badge work-badge--${traceTone(stage.status)}`}>{stage.status}</span>
        </summary>
        <div className="coding-pipeline-stage__body">
          <KeyValue label="Failure taxonomy" value={stage.failure_type || "-"} />
          <KeyValue label="Duration" value={stage.duration_ms ? `${stage.duration_ms}ms` : "-"} />
          {stage.log_excerpt?.text ? (
            <div className="coding-detail__wide">
              <h3>Log excerpt {stage.log_excerpt.truncated ? "(truncated)" : ""}</h3>
              <pre>{stage.log_excerpt.text}</pre>
            </div>
          ) : null}
          <TraceJson title="Artifacts" value={stage.artifacts} />
          <TraceJson title="Test report" value={stage.test_report} />
          <TraceJson title="Coverage" value={stage.coverage} />
          <TraceJson title="Scan report" value={stage.scan_report} />
        </div>
      </details>
    </li>
  );
}

function TraceJson({ title, value }: { title: string; value: unknown }) {
  if (value == null || (Array.isArray(value) && value.length === 0)) {
    return null;
  }
  if (typeof value === "object" && !Array.isArray(value) && Object.keys(value as Record<string, unknown>).length === 0) {
    return null;
  }
  return (
    <section className="coding-detail__wide">
      <h3>{title}</h3>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <dl className="coding-detail__kv">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </dl>
  );
}

function traceTone(status: string) {
  if (["failed", "blocked", "unstable", "error"].includes(status)) return "danger";
  if (["passed", "success", "completed"].includes(status)) return "active";
  if (["running", "queued", "pending"].includes(status)) return "running";
  return "neutral";
}
