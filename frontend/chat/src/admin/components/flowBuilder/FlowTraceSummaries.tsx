// Read-only summaries of one step run: decision trace, tool evidence and raw blocks.
import {
  asRecord,
  compactToolExample,
  compactValue,
  prettyTraceJson,
  statusClass,
  toolResultsFromOutput,
} from "./flowTraceFormat";

export function DecisionTraceSummary({ value }: { value: unknown }) {
  const trace = asRecord(value);
  if (!Object.keys(trace).length) return null;
  const basis = asRecord(trace.basis);
  const source = asRecord(trace.source);
  const nextAction = asRecord(trace.next_action);
  const evidenceRefs = Array.isArray(basis.evidence_refs) ? basis.evidence_refs.slice(0, 5) : [];
  const artifactRefs = Array.isArray(basis.artifact_refs) ? basis.artifact_refs.slice(0, 5) : [];
  return (
    <div className="flow-builder__decision-trace">
      <div className="flow-builder__trace-detail-head">
        <div>
          <strong>Decision trace</strong>
          <span>{compactValue(source.kind)} · {compactValue(nextAction.action)}</span>
        </div>
        <span>{compactValue(trace.kind)}</span>
      </div>
      {basis.rationale ? <p>{compactValue(basis.rationale)}</p> : null}
      <div className="flow-builder__decision-grid">
        <span>Source</span>
        <strong>{compactValue(source.tool ?? source.session_id ?? source.selected_route ?? source.kind)}</strong>
        <span>Next</span>
        <strong>{compactValue(nextAction.route ?? nextAction.reason ?? nextAction.action)}</strong>
        <span>Evidence</span>
        <strong>{evidenceRefs.length || compactValue(asRecord(basis.evidence_summary).count ?? asRecord(basis.evidence_summary).evidence_count ?? "summary")}</strong>
        <span>Artifacts</span>
        <strong>{artifactRefs.length}</strong>
      </div>
      {evidenceRefs.length ? (
        <ul className="flow-builder__decision-evidence">
          {evidenceRefs.map((item, index) => (
            <li key={index}>{compactToolExample(item)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function ToolEvidenceSummary({ output }: { output: unknown }) {
  const tools = toolResultsFromOutput(output);
  if (!tools.length) return null;
  return (
    <div className="flow-builder__tool-evidence">
      <div className="flow-builder__tool-evidence-head">
        <span>Tool evidence</span>
        <strong>{tools.length} call{tools.length === 1 ? "" : "s"}</strong>
      </div>
      {tools.map((tool, index) => {
        const summary = asRecord(tool.summary);
        const params = asRecord(tool.params);
        const examples = Array.isArray(summary.examples) ? summary.examples.slice(0, 3) : [];
        const status = String(tool.status || "unknown");
        return (
          <article className="flow-builder__tool-card" key={`${String(tool.tool_name || "tool")}-${index}`}>
            <div className="flow-builder__tool-card-top">
              <strong>{String(tool.tool_name || "tool")}</strong>
              <span className={`flow-builder__badge ${statusClass(status)}`}>{status}</span>
            </div>
            <div className="flow-builder__tool-meta">
              <span>{compactValue(summary.count ?? summary.evidence_count ?? examples.length)} matches</span>
              <span>{compactValue(params.query ?? params.user ?? params.author ?? params.jql ?? params.cql)} query</span>
            </div>
            {tool.error ? <div className="flow-builder__trace-error">{String(tool.error)}</div> : null}
            {examples.length ? (
              <ul className="flow-builder__tool-examples">
                {examples.map((example, exampleIndex) => (
                  <li key={exampleIndex}>{compactToolExample(example)}</li>
                ))}
              </ul>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

export function TraceBlock({ title, value }: { title: string; value: unknown }) {
  return (
    <details className="flow-builder__trace-block" open={title === "Input" || title === "Output"}>
      <summary>{title}</summary>
      <pre>{prettyTraceJson(value)}</pre>
    </details>
  );
}
