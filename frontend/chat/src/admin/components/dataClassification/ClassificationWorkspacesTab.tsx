import { LevelTag } from "../settingsKit/SettingsKit";

export type ClassifiedWorkspace = { id: string; name: string; level: string | null; source: string; overrides?: Record<string, unknown> };

const SOURCE_TEXT: Record<string, string> = { workspace: "Own", instance_default: "Default", unset: "–" };

// Each Workspace's level and where it came from. A Workspace without a level gets the published
// level for new Workspaces with one click (its own level, written through the Workspace classification route).
export function ClassificationWorkspacesTab({ workspaces, levelLabel, levelColor, publishedDefault, editable, busy, onApply,
  overrideChips, onEdit }: {
  workspaces: ClassifiedWorkspace[] | null;
  levelLabel: (key: string) => string;
  levelColor: (key: string) => string | null;
  publishedDefault: string | null;
  editable: boolean;
  busy: boolean;
  onApply: (workspaceId: string) => void;
  overrideChips: (workspace: ClassifiedWorkspace) => string[];
  onEdit: (workspace: ClassifiedWorkspace) => void;
}) {
  return (
    <div className="sk-page">
      <p className="sk-hint">A Workspace has one level. Overrides can only make a rule <b>stricter</b> than its level.</p>
      <table className="admin-panel__table sk-cards" data-testid="classification-workspaces">
        <thead><tr><th>Workspace</th><th>Level</th><th>Source</th><th>Stricter overrides</th><th /></tr></thead>
        <tbody>
          {workspaces === null ? <tr><td colSpan={5} className="admin-panel__cell--muted">Loading…</td></tr>
            : workspaces.length === 0 ? <tr><td colSpan={5} className="admin-panel__cell--muted">No active Workspace.</td></tr>
              : workspaces.map((workspace) => (
                <tr key={workspace.id}>
                  <td data-label="Workspace">{workspace.name}</td>
                  <td data-label="Level">
                    {workspace.level ? <LevelTag label={levelLabel(workspace.level)} color={levelColor(workspace.level)} />
                      : <span className="work-badge work-badge--danger">No level</span>}
                  </td>
                  <td data-label="Source">{SOURCE_TEXT[workspace.source] ?? workspace.source}</td>
                  <td data-label="Overrides">
                    {overrideChips(workspace).length
                      ? <span className="sk-chips">{overrideChips(workspace).map((chip) => <span key={chip} className="admin-policy-chip admin-policy-chip--secondary">{chip}</span>)}</span>
                      : <span className="admin-panel__cell--muted">–</span>}
                  </td>
                  <td>
                    {workspace.level && editable ? (
                      <button type="button" className="admin-panel__action-btn" data-testid={`classification-edit-${workspace.id}`}
                        onClick={() => onEdit(workspace)}>Edit</button>
                    ) : null}
                    {!workspace.level && editable && publishedDefault ? (
                      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
                        data-testid={`classification-apply-${workspace.id}`} onClick={() => onApply(workspace.id)}>
                        Apply {levelLabel(publishedDefault)}
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}
