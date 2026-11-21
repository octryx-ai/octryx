// Presentational parts of the run result: outcome line, notices, the terminal result,
// and the collapsed raw result / diagnostics. All content comes from flowRunResult.ts.
import type { DiagnosticRow, FlowRunResultView, RunNotice, RunResultBody } from "./flowRunResult";
import type { FlowRunStepCounts } from "./flowRunStepCounts";
import { prettyTraceJson } from "./flowTraceFormat";
import "./flowRunResult.css";

// Outcome, duration and the steps by status ("3 completed · 1 skipped"), with retries noted;
// rows are attempts, so they are never all called executed.
export function RunOutcome({ view, steps }: { view: FlowRunResultView; steps: FlowRunStepCounts }) {
  return (
    <p className={`flow-run-result__outcome flow-run-result__outcome--${view.tone}`}>
      <strong>{view.outcome}</strong>
      {view.duration ? <span>in {view.duration}</span> : null}
      <span data-testid="flow-run-step-counts">
        {steps.summary}
        {steps.attemptsNote ? ` (${steps.attemptsNote})` : ""}
      </span>
    </p>
  );
}

export function RunNotices({ notices }: { notices: RunNotice[] }) {
  if (!notices.length) return null;
  return (
    <div className="flow-run-result__notices">
      {notices.map((notice, index) => (
        <div
          key={`${notice.tone}-${index}`}
          className={`flow-run-result__notice flow-run-result__notice--${notice.tone}`}
          role={notice.tone === "error" ? "alert" : "status"}
        >
          <strong>{notice.title}</strong>
          {notice.detail ? <p>{notice.detail}</p> : null}
        </div>
      ))}
    </div>
  );
}

export function RunResultContent({ result }: { result: RunResultBody }) {
  if (result.kind === "none") return null;
  if (result.kind === "message") return <p className="flow-run-result__message">{result.text}</p>;
  return (
    <div className="flow-run-result__body" aria-label={result.heading}>
      <span className="flow-run-result__heading">{result.heading}</span>
      {result.kind === "fields" ? (
        <dl className="flow-run-result__fields">
          {result.fields.map((field) => (
            <div key={field.label}>
              <dt>{field.label}</dt>
              <dd className={field.multiline ? "flow-run-result__multiline" : undefined}>{field.value}</dd>
            </div>
          ))}
        </dl>
      ) : result.kind === "list" ? (
        <ul className="flow-run-result__list">
          {result.items.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="flow-run-result__multiline">{result.text}</p>
      )}
    </div>
  );
}

export function RawResult({ raw }: { raw: Record<string, unknown> | null }) {
  if (!raw) return null;
  return (
    <details className="flow-run-panel__section">
      <summary>Advanced: raw result</summary>
      <pre className="flow-run-result__raw">{prettyTraceJson(raw)}</pre>
    </details>
  );
}

export function RunDiagnostics({ rows, rawFacts }: { rows: DiagnosticRow[]; rawFacts: Record<string, unknown> }) {
  return (
    <details className="flow-run-panel__section">
      <summary>Diagnostics</summary>
      <dl className="flow-run-result__fields flow-run-result__fields--compact">
        {rows.map((row) => (
          <div key={row.label}>
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      <details className="flow-run-result__raw-facts">
        <summary>Raw run facts</summary>
        <pre className="flow-run-result__raw">{prettyTraceJson(rawFacts)}</pre>
      </details>
    </details>
  );
}
