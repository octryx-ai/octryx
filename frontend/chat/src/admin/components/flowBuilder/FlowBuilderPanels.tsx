import type { FlowValidationReport } from "./flowBuilderTypes";
import { readinessLabel } from "./flowNextAction";

export function FlowReadiness({
  report,
  publishReady,
  onIssueFocus,
}: {
  report: FlowValidationReport;
  publishReady: boolean;
  onIssueFocus?: (issue: { code: string; message: string }) => void;
}) {
  const issues = [...(report.errors || []), ...(report.warnings || [])];
  return (
    <div className="flow-builder__readiness">
      <div>
        <span className="admin-panel__section-title">Publish readiness</span>
        <p className="admin-panel__muted">
          {publishReady
            ? "The current draft passed validation and can be published."
            : report.valid
              ? "Validation passed. Only a saved, unpublished draft revision can be published."
              : "Validate the draft and resolve blocking errors before publish."}
        </p>
      </div>
      <div className="flow-builder__metrics">
        <span>{report.node_count} nodes</span>
        <span>{report.edge_count} edges</span>
        <span>{readinessLabel(report)}</span>
      </div>
      {issues.length ? (
        <ul className="flow-builder__issues">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`}>
              <button
                type="button"
                onClick={() => onIssueFocus?.(issue)}
                disabled={!onIssueFocus}
              >
                <strong>{issue.code}</strong> {issue.message}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
