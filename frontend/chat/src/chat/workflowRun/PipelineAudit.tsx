import { StatusLabel } from "../../layout/StatusLabel";
import { pipelineAuditView, type RunPipeline } from "./pipelineAuditModel";

// The pipeline's audit on the run view: one line (how many commands, from which declaration, on which commit), the
// reason when the environment file stopped it, and the commands and folder folded away.
export function PipelineAudit({ pipeline }: { pipeline?: RunPipeline | null }) {
  const view = pipelineAuditView(pipeline);
  if (!view) return null;
  return (
    <section className="pipeline-audit" aria-label="Pipeline" data-testid="workflow-run-pipeline">
      <p className="run-bar__text pipeline-audit__summary">
        <StatusLabel label={view.label} tone={view.tone} /> <span>{view.summary}</span>
      </p>
      {view.problem ? <p className="run-bar__text" role="alert">{view.problem}</p> : null}
      {view.errors.length ? (
        <ul className="pipeline-audit__code" aria-label="File errors">
          {view.errors.map((error) => <li key={error}>{error}</li>)}
        </ul>
      ) : null}
      {view.setup.map((line) => <pre key={line} className="pipeline-audit__code">{line}</pre>)}
      {view.details.length ? (
        <details className="workflow-run-banner__details">
          <summary>Commands and folder</summary>
          <ul className="workflow-run-banner__details-list pipeline-audit__mono">
            {view.details.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
