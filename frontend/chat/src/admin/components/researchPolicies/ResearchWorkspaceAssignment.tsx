import type { ProjectOption } from "../../../chatOptionTypes";
import type {
  ResearchPolicyProfile,
  ResearchPolicyVersion,
  WorkspaceResearchPolicyPayload,
} from "../../types/researchPolicyTypes";
import { ChooseWorkspaceLine } from "../../../chat/workspace/ChooseWorkspaceLine";
import { diagnosticsWords, effectiveSourceWords, researchProfileSummary } from "./researchProfileSummary";

type ResearchWorkspaceAssignmentProps = {
  projects: ProjectOption[];
  selectedProjectId: string;
  workspacePolicy: WorkspaceResearchPolicyPayload | null;
  publishedVersions: Array<{ profile: ResearchPolicyProfile; version: ResearchPolicyVersion }>;
  saving: boolean;
  onAssign: (profileVersionId: string) => void;
  onClear: () => void;
};

// Which research profile a workspace uses. The workspace comes from the shared
// active workspace (the one switch at the head of the rail);
// this page has no select of its own. The research websites
// themselves live under Knowledge; the page help links them (no hint text).
export function ResearchWorkspaceAssignment({
  projects,
  selectedProjectId,
  workspacePolicy,
  publishedVersions,
  saving,
  onAssign,
  onClear,
}: ResearchWorkspaceAssignmentProps) {
  const assignedVersionId =
    workspacePolicy?.assignment?.assignment_status === "active"
      ? workspacePolicy.assignment.profile_version_id
      : "";
  const effective = workspacePolicy?.effective_policy;

  return (
    <>
      <div className="admin-panel__section-header" style={{ marginTop: "1.5rem" }}>
        <span>Workspace assignment</span>
      </div>
      {!selectedProjectId ? (
        <ChooseWorkspaceLine projects={projects} purpose="to see and change its research profile" />
      ) : (
        <div className="admin-card research-assignment">
          <p className="research-assignment__effective">
            In effect: <strong>{effective?.profile_name || "Default policy"}</strong>
            {effective?.version ? ` · v${effective.version}` : ""}
            <span className="admin-panel__cell--muted">
              {" "}
              · {effectiveSourceWords(effective?.source)}
              {diagnosticsWords(workspacePolicy?.diagnostics.status)}
            </span>
          </p>
          <p className="admin-panel__hint">
            Allows: {researchProfileSummary(effective?.spec)}
          </p>
          <div className="admin-form-field">
            <label className="admin-form-field__label" htmlFor="research-assignment-version">
              Assigned profile
            </label>
            <select
              id="research-assignment-version"
              className="admin-panel__input"
              value={assignedVersionId}
              disabled={saving}
              onChange={(e) => {
                if (e.target.value) onAssign(e.target.value);
              }}
            >
              <option value="">Use default deep research policy</option>
              {publishedVersions.map(({ profile, version }) => (
                <option key={version.id} value={version.id}>
                  {profile.name} · v{version.version}
                </option>
              ))}
            </select>
          </div>
          <div className="admin-panel__form-actions">
            <button
              type="button"
              className="admin-panel__action-btn"
              disabled={saving || !assignedVersionId}
              onClick={onClear}
            >
              Clear workspace assignment
            </button>
          </div>
        </div>
      )}
    </>
  );
}
