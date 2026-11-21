import type { PanelTaskDependencyRow, PanelTaskDependencyStateRow } from "./taskTypes";

export function AdminTaskDependencyGraph({
  dependencyState,
  dependencyTarget,
  dependencyCondition,
  onDependencyTargetChange,
  onDependencyConditionChange,
  onAddDependency,
  onDeleteDependency,
}: {
  dependencyState: PanelTaskDependencyStateRow | undefined;
  dependencyTarget: string;
  dependencyCondition: string;
  onDependencyTargetChange: (value: string) => void;
  onDependencyConditionChange: (value: string) => void;
  onAddDependency: () => void;
  onDeleteDependency: (dependencyId: string) => void;
}) {
  const dependencies = dependencyState?.dependencies || [];
  const dependents = dependencyState?.dependents || [];
  const availableTasks = dependencyState?.available_tasks || [];

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--ds-radius-lg)",
        padding: "0.9rem",
        marginBottom: "1rem",
        background: "var(--panel-elevated, rgba(255,255,255,0.02))",
      }}
    >
      <div
        style={{
          display: "grid",
          gap: "0.9rem",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        }}
      >
        <UpstreamList dependencies={dependencies} onDeleteDependency={onDeleteDependency} />

        <DownstreamList dependents={dependents} />
      </div>

      <AddDependencyRow
        availableTasks={availableTasks}
        dependencyTarget={dependencyTarget}
        dependencyCondition={dependencyCondition}
        onDependencyTargetChange={onDependencyTargetChange}
        onDependencyConditionChange={onDependencyConditionChange}
        onAddDependency={onAddDependency}
      />
    </div>
  );
}

function UpstreamList({
  dependencies,
  onDeleteDependency,
}: {
  dependencies: PanelTaskDependencyRow[];
  onDeleteDependency: (dependencyId: string) => void;
}) {
  return (
    <div>
      <div className="admin-panel__form-label">Depends on</div>
      {dependencies.length === 0 ? (
        <div className="admin-panel__cell--muted">
          No upstream dependencies.
        </div>
      ) : (
        <div className="steps-list">
          {dependencies.map((dependency) => (
            <div
              key={dependency.id}
              className="step-item"
              style={{ padding: "0.65rem 0.8rem" }}
            >
              <div className="step-item__main">
                <div className="step-item__name">
                  {dependency.depends_on_task_name}
                </div>
                <div className="step-item__meta">
                  Runs when upstream action is {dependency.condition}
                </div>
              </div>
              <button
                type="button"
                className="admin-panel__danger-btn"
                onClick={() => onDeleteDependency(dependency.id)}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DownstreamList({ dependents }: { dependents: PanelTaskDependencyRow[] }) {
  return (
    <div>
      <div className="admin-panel__form-label">Required by</div>
      {dependents.length === 0 ? (
        <div className="admin-panel__cell--muted">
          No downstream actions.
        </div>
      ) : (
        <div className="steps-list">
          {dependents.map((dependency) => (
            <div
              key={dependency.id}
              className="step-item"
              style={{ padding: "0.65rem 0.8rem" }}
            >
              <div className="step-item__main">
                <div className="step-item__name">
                  {dependency.task_name}
                </div>
                <div className="step-item__meta">
                  Waits for this action with condition{" "}
                  {dependency.condition}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AddDependencyRow({
  availableTasks,
  dependencyTarget,
  dependencyCondition,
  onDependencyTargetChange,
  onDependencyConditionChange,
  onAddDependency,
}: {
  availableTasks: PanelTaskDependencyStateRow["available_tasks"];
  dependencyTarget: string;
  dependencyCondition: string;
  onDependencyTargetChange: (value: string) => void;
  onDependencyConditionChange: (value: string) => void;
  onAddDependency: () => void;
}) {
  return (
    <div
      style={{
        display: "grid",
        gap: "0.75rem",
        gridTemplateColumns: "minmax(0, 1.6fr) minmax(0, 1fr) auto",
        marginTop: "0.9rem",
      }}
    >
      <select
        value={dependencyTarget}
        onChange={(event) => onDependencyTargetChange(event.target.value)}
        className="connector-field__input"
      >
        <option value="">Select upstream action…</option>
        {availableTasks.map((task) => (
          <option key={task.id} value={task.id}>
            {task.name}
          </option>
        ))}
      </select>

      <select
        value={dependencyCondition}
        onChange={(event) => onDependencyConditionChange(event.target.value)}
        className="connector-field__input"
      >
        <option value="success">on success</option>
        <option value="failure">on failure</option>
        <option value="always">on completion</option>
      </select>

      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={onAddDependency}
      >
        + Add dependency
      </button>
    </div>
  );
}
