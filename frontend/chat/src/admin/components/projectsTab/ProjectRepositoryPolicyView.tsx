// Repository operation policy view of the project resources: one card per repository with operation toggles.
import type { ProjectResourcePayload, RepositoryResource } from "./projectResourcesTypes";

const OPERATION_LABELS: Record<string, string> = {
  read: "Read",
  branch: "Branch",
  write: "Write",
  pr: "Pull request",
  index: "Index",
  migration: "Migration",
};

export function ProjectRepositoryPolicyView({
  payload,
  saving,
  toggleRepositoryOperation,
}: {
  payload: ProjectResourcePayload;
  saving: boolean;
  toggleRepositoryOperation: (repository: RepositoryResource, operationKey: string) => void;
}) {
  return (
    <div className="admin-modal__stack">
      <div className="admin-panel__section-header">
        <span>Repository operation policy</span>
      </div>
      <p className="admin-panel__hint">
        Connector settings define what the platform can reach. These project
        policies define which repository operations this project may use.
      </p>
      {payload.repositories.length === 0 ? (
        <div className="admin-panel__empty-state">
          No repositories are assigned to this project yet. Add project
          repositories in the Repositories section before configuring
          operation policy.
        </div>
      ) : null}
      <div className="connector-grid">
        {payload.repositories.map((repo) => (
          <div
            key={repo.id}
            className="connector-card connector-card--configured"
          >
            <div className="connector-card__header">
              <div className="connector-card__info">
                <div className="connector-card__name-row">
                  <div className="connector-card__name">{repo.name}</div>
                  <span className="connector-card__meta-badge">
                    {repo.provider}
                  </span>
                </div>
                <div className="connector-card__meta">{repo.repo_root}</div>
              </div>
            </div>
            <div className="task-item__runs" style={{ paddingTop: 0 }}>
              <div className="admin-inline-actions">
                {payload.policy_keys.map((key) => (
                  <label key={key} className="admin-checkbox-row">
                    <input
                      type="checkbox"
                      checked={Boolean(repo.operation_policy[key])}
                      disabled={saving}
                      onChange={() => toggleRepositoryOperation(repo, key)}
                    />
                    <span>{OPERATION_LABELS[key] || key}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
