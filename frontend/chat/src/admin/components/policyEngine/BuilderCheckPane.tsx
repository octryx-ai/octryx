import type { ReactNode } from "react";

import type { TestReport } from "./policyEngineVersions";

// Step 6 "Check & save": whether the generated policy validates, what it would block (examples,
// added by the caller), and the saved test cases that run on every save and again at publish.
export function BuilderCheckPane({ valid, schemaVersion, report, examples, traffic }: {
  valid: boolean;
  schemaVersion: string;
  report: TestReport | null;
  examples?: ReactNode;
  /** What the saved policy would block in live traffic (draft shadow). */
  traffic?: ReactNode;
}) {
  return (
    <section className="admin-panel__card policies__pane" data-testid="builder-pane-check">
      <div className="admin-panel__section-header"><span>Check &amp; save</span>
        <span className={`work-badge ${valid ? "work-badge--active" : "work-badge--attention"}`} data-testid="builder-check-valid">{valid ? "Valid" : "Not valid yet"}</span></div>
      <p className="admin-panel__hint">
        {valid ? `The generated Cedar validates against schema ${schemaVersion} and is a forbid with a unique @id.`
          : "Complete the steps marked on the right; the server checks the generated Cedar while you edit."}
      </p>
      {examples ?? (
        <div className="admin-panel__section-header"><span>Saved test cases</span>
          {report && report.total ? <span className={`work-badge ${report.ok ? "work-badge--active" : "work-badge--danger"}`} data-testid="builder-check-cases">{report.passed} / {report.total} pass</span>
            : <span className="work-badge work-badge--neutral" data-testid="builder-check-cases">None saved</span>}</div>
      )}
      <p className="admin-panel__hint">Saved cases run on every draft save and again at publish; a failing case blocks publishing.</p>
      {traffic ? (
        <>
          <div className="admin-panel__section-header"><span>Real traffic (last 24 h)</span><span className="work-badge work-badge--neutral">Draft shadow</span></div>
          {traffic}
        </>
      ) : null}
    </section>
  );
}
