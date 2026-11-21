import { useState } from "react";

import { StatusLabel } from "../layout/StatusLabel";
import { findingWhere, openFindingsView, severityLabel, SEVERITY_TONES } from "../chat/workflowRun/openFindingsModel";

// The review findings a run went on with (on_open_high: continue_with_findings), on the phone's run page under the
// state: decided on the pull request, so they are shown, not answered.
export function OpenFindings({ value }: { value: unknown }) {
  const [all, setAll] = useState(false);
  const view = openFindingsView(value, all);
  if (!view) return null;
  return (
    <section aria-labelledby="m-open-findings" data-testid="m-run-open-findings">
      <h2 id="m-open-findings" className="m-section">
        Open review findings
      </h2>
      <p className="m-section-hint">The run went on with these. Decide them on the pull request.</p>
      <div className="m-decision-group">
        {view.findings.map((finding, index) => (
          <div className="m-finding" key={`${finding.file}:${finding.line}:${index}`}>
            <div className="m-finding-head">
              <StatusLabel label={severityLabel(finding.severity)} tone={SEVERITY_TONES[finding.severity] ?? "neutral"} />
              {findingWhere(finding) && <code title={finding.file}>{findingWhere(finding)}</code>}
            </div>
            {finding.summary && <p>{finding.summary}</p>}
            {finding.fix && <p className="m-muted m-finding-fix">{finding.fix}</p>}
          </div>
        ))}
        {view.more && (
          <button type="button" className="m-text-button" onClick={() => setAll(true)}>
            {view.more}
          </button>
        )}
      </div>
    </section>
  );
}
