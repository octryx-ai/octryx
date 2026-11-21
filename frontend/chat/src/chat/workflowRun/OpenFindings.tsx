import { useState } from "react";

import { StatusLabel } from "../../layout/StatusLabel";
import { findingWhere, openFindingsView, severityLabel, SEVERITY_TONES } from "./openFindingsModel";

// The review findings the run went on with (on_open_high: continue_with_findings), under the history line that says
// so: severity, where, what is wrong and, muted, the proposed fix. Decided on the pull request, not here.
export function OpenFindings({ value }: { value: unknown }) {
  const [all, setAll] = useState(false);
  const view = openFindingsView(value, all);
  if (!view) return null;
  return (
    <div className="open-findings" data-testid="workflow-run-open-findings">
      <ul className="open-findings__list" aria-label={`Open review findings (${view.total})`}>
        {view.findings.map((finding, index) => (
          <li key={`${finding.file}:${finding.line}:${index}`} className="open-findings__item">
            <div className="open-findings__head">
              <StatusLabel label={severityLabel(finding.severity)} tone={SEVERITY_TONES[finding.severity] ?? "neutral"} />
              {findingWhere(finding) ? (
                <code className="open-findings__place" title={finding.file}>{findingWhere(finding)}</code>
              ) : null}
            </div>
            {finding.summary ? <p className="open-findings__summary">{finding.summary}</p> : null}
            {finding.fix ? <p className="open-findings__fix">{finding.fix}</p> : null}
          </li>
        ))}
      </ul>
      {view.more ? (
        <button type="button" className="decision-card__link" onClick={() => setAll(true)}>{view.more}</button>
      ) : null}
    </div>
  );
}
