// Admin › Scenarios: the basic fields (name, scope, priority, status, description) of the scenario modal.
import type { Dispatch, SetStateAction } from "react";
import { SectionBlock } from "./ScenarioFormControls";

type ProjectOptionRow = {
  id: string;
  name: string;
};

type Props = {
  projects: ProjectOptionRow[];
  scenarioName: string;
  setScenarioName: Dispatch<SetStateAction<string>>;
  scenarioProjectId: string;
  setScenarioProjectId: Dispatch<SetStateAction<string>>;
  scenarioPriority: number;
  setScenarioPriority: Dispatch<SetStateAction<number>>;
  scenarioActive: boolean;
  setScenarioActive: Dispatch<SetStateAction<boolean>>;
  scenarioDescription: string;
  setScenarioDescription: Dispatch<SetStateAction<string>>;
};

/** Global or one project. */
function ScenarioScopeField({ projects, scenarioProjectId, setScenarioProjectId }: Pick<
  Props, "projects" | "scenarioProjectId" | "setScenarioProjectId"
>) {
  return (
    <div className="admin-form-field">
      <label htmlFor="scenario-project">Project scope</label>
      <select
        id="scenario-project"
        className="connector-field__input"
        value={scenarioProjectId}
        onChange={(e) => setScenarioProjectId(e.target.value)}
      >
        <option value="">Global (all projects)</option>
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/** The active toggle and what it means for matching. */
function ScenarioStatusField({ scenarioActive, setScenarioActive }: Pick<Props, "scenarioActive" | "setScenarioActive">) {
  return (
    <div className="admin-form-field">
      <label>Status</label>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          marginTop: "0.2rem",
        }}
      >
        <button
          type="button"
          className={`admin-panel__toggle ${scenarioActive ? "admin-panel__toggle--on" : "admin-panel__toggle--off"}`}
          onClick={() => setScenarioActive((v) => !v)}
          aria-label="Toggle active"
        >
          <span />
        </button>
        <span
          style={{
            fontSize: "var(--ds-text-xs)",
            color: scenarioActive ? "var(--status-active)" : "var(--text-muted)",
          }}
        >
          {scenarioActive
            ? "Active — participates in matching"
            : "Inactive — ignored"}
        </span>
      </div>
    </div>
  );
}

export function ScenarioBasicSection({
  projects,
  scenarioName,
  setScenarioName,
  scenarioProjectId,
  setScenarioProjectId,
  scenarioPriority,
  setScenarioPriority,
  scenarioActive,
  setScenarioActive,
  scenarioDescription,
  setScenarioDescription,
}: Props) {
  return (
    <SectionBlock title="Basic">
      <div className="admin-form-grid">
        <div className="admin-form-field">
          <label htmlFor="scenario-name">Name</label>
          <input
            id="scenario-name"
            className="connector-field__input"
            value={scenarioName}
            onChange={(e) => setScenarioName(e.target.value)}
            placeholder="e.g. Jira-heavy research"
            required
          />
        </div>
        <ScenarioScopeField projects={projects} scenarioProjectId={scenarioProjectId}
          setScenarioProjectId={setScenarioProjectId} />
        <div className="admin-form-field">
          <label htmlFor="scenario-priority">Priority</label>
          <input
            id="scenario-priority"
            type="number"
            className="connector-field__input"
            value={scenarioPriority}
            onChange={(e) =>
              setScenarioPriority(Number(e.target.value) || 0)
            }
          />
          <span className="admin-form-help">
            Higher priority wins when multiple profiles match.
          </span>
        </div>
        <ScenarioStatusField scenarioActive={scenarioActive} setScenarioActive={setScenarioActive} />
        <div className="admin-form-field admin-form-grid__full">
          <label htmlFor="scenario-description">Description</label>
          <textarea
            id="scenario-description"
            className="connector-field__input connector-field__input--textarea"
            value={scenarioDescription}
            onChange={(e) => setScenarioDescription(e.target.value)}
            placeholder="Describe the intent of this scenario profile."
            rows={2}
          />
        </div>
      </div>
    </SectionBlock>
  );
}
