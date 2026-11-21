// What a waiting run asks the person to decide on, on the phone (the web's RunPayload, same model: payloadView): the
// facts as lines, the agent's text (for a spec interview: the whole question round with its defaults), and what blocks
// a confirm. A long text shows its first lines and opens in place with "Show all"; nothing is cut.

import { useState } from "react";
import { FOLD_AT, foldPreview } from "../chat/workflowRun/workflowRunModel";
import { type PayloadView } from "../chat/workflowRun/workflowRunPayloadView";

export function RunPayload({ view, showHeading = true }: { view: PayloadView | null; showHeading?: boolean }) {
  const [open, setOpen] = useState(false);
  if (!view) return null;
  const long = Boolean(view.text && view.text.length > FOLD_AT);
  const hasContent =
    view.testAlert || view.missing || view.lines.length || view.text || view.blockers.length;
  if (!hasContent) return null;
  return (
    <div className="m-payload" data-testid="m-run-payload">
      {showHeading && <h3 className="m-section">{view.heading}</h3>}
      {view.testAlert && <p className="m-payload-alert">{view.testAlert}</p>}
      {view.missing && <p className="m-muted">{view.missing}</p>}
      {view.lines.length > 0 && (
        <ul className="m-payload-lines">
          {view.lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {view.text && (
        <>
          <p className="m-note" data-testid="m-run-payload-text">
            {long && !open ? foldPreview(view.text) : view.text}
          </p>
          {long && (
            <button type="button" className="m-payload-more" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
              {open ? "Show less" : `Show all (${view.text.length.toLocaleString()} characters)`}
            </button>
          )}
        </>
      )}
      {view.blockers.length > 0 && (
        <ul className="m-payload-lines" aria-label="Not yet confirmable">
          {view.blockers.map((line) => (
            <li key={line} className="m-error">
              {line}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
