import type { WorkspaceDiagnosticsWarning } from "../../../types/workspaceCompositionTypes";
import type { ProjectSettingsTab } from "../projectSettingsSections";
import { presentWorkspaceDiagnostic } from "../workspaceDiagnosticsPresenter";

// Workspace diagnostics: each warning reads as impact + fix with a link to
// the section that resolves it. The raw code stays visible for support.
type WorkspaceDiagnosticsPanelProps = {
  warnings: WorkspaceDiagnosticsWarning[];
  runtimeAssignmentMode: string;
  onOpenSection?: (section: ProjectSettingsTab) => void;
};

export function WorkspaceDiagnosticsPanel({
  warnings,
  runtimeAssignmentMode,
  onOpenSection,
}: WorkspaceDiagnosticsPanelProps) {
  if (warnings.length === 0) {
    return (
      <div className="admin-panel__empty-state">
        No configuration problems are reported for this workspace.
      </div>
    );
  }
  return (
    <ul className="workspace-diagnostics">
      {warnings.map((warning) => {
        const view = presentWorkspaceDiagnostic(warning, runtimeAssignmentMode);
        return (
          <li key={warning.code} className="workspace-diagnostics__item">
            <div className="workspace-diagnostics__header">
              <strong>{view.title}</strong>
              <span
                className={`admin-panel__badge ${view.severity === "error" ? "admin-panel__badge--danger" : "admin-panel__badge--warning"}`}
              >
                {view.severity === "error" ? "Blocking" : "Warning"}
              </span>
            </div>
            <p>
              <span className="workspace-diagnostics__label">Impact</span> {view.impact}
            </p>
            {view.fix ? (
              <p>
                <span className="workspace-diagnostics__label">Fix</span> {view.fix}
              </p>
            ) : null}
            <div className="workspace-diagnostics__footer">
              <code className="workspace-diagnostics__code">{view.code}</code>
              {view.fixSection && onOpenSection ? (
                <button
                  type="button"
                  className="admin-projects__row-action"
                  onClick={() => onOpenSection(view.fixSection as ProjectSettingsTab)}
                >
                  {view.fixLabel}
                </button>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
