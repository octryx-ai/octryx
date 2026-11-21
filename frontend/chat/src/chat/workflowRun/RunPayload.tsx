import { FOLD_AT, foldPreview } from "./workflowRunModel";
import { type PayloadView } from "./workflowRunPayloadView";

// The typed payload a confirmation decides on: the test contract's criteria with their commands, a drafted
// text, or the facts of the next step; what blocks a confirm is listed, never hidden.
export function RunPayload({ view }: { view: PayloadView | null }) {
  if (!view) return null;
  return (
    <div className="workflow-run-banner__payload">
      <div className="resume-notice__title">{view.heading}</div>
      {view.testAlert ? (
        <div className="resume-notice__body">
          <strong>{view.testAlert}</strong>
        </div>
      ) : null}
      {view.missing ? (
        <div className="resume-notice__body">{view.missing}</div>
      ) : null}
      {view.lines.length ? (
        <ul className="workflow-run-list">
          {view.lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {view.text && view.text.length > FOLD_AT ? (
        <details className="workflow-run-banner__fold" data-testid="run-payload-fold">
          <summary>
            <pre className="workflow-run-banner__text">{foldPreview(view.text)}</pre>
            <span className="workflow-run-banner__fold-more">Show the whole answer ({view.text.length.toLocaleString()} characters)</span>
          </summary>
          <pre className="workflow-run-banner__text">{view.text}</pre>
        </details>
      ) : view.text ? (
        <pre className="workflow-run-banner__text">{view.text}</pre>
      ) : null}
      {view.blockers.length ? (
        <ul className="workflow-run-list" aria-label="Not yet confirmable">
          {view.blockers.map((line) => (
            <li key={line} className="workspace__error">
              {line}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
