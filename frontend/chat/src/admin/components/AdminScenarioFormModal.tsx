// Admin › Scenarios: the create and edit modal of a routing scenario.
import type { Dispatch, FormEvent, SetStateAction } from "react";
import { ScenarioBasicSection } from "./ScenarioBasicSection";
import { ScenarioExecutionSection, ScenarioMatchSection, ScenarioPlannerSection } from "./ScenarioConfigSections";
import { useScenarioConfigState } from "./useScenarioConfigState";

type ProjectOptionRow = {
  id: string;
  name: string;
};

type AdminScenarioFormModalProps = {
  show: boolean;
  editingScenarioId: string | null;
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
  scenarioMatchConfig: string;
  setScenarioMatchConfig: Dispatch<SetStateAction<string>>;
  scenarioPlannerConfig: string;
  setScenarioPlannerConfig: Dispatch<SetStateAction<string>>;
  scenarioExecutionConfig: string;
  setScenarioExecutionConfig: Dispatch<SetStateAction<string>>;
  scenarioFormError: string | null;
  scenarioFormLoading: boolean;
  onSaveScenario: (event: FormEvent) => void | Promise<void>;
  onClose: () => void;
};

// ─── Main modal ──────────────────────────────────────────────────────────────

export function AdminScenarioFormModal(props: AdminScenarioFormModalProps) {
  const { show, editingScenarioId, scenarioFormError, scenarioFormLoading, onSaveScenario, onClose } = props;
  const { match, planner, execution, syncMatch, syncPlanner, syncExecution } = useScenarioConfigState(props);

  if (!show) return null;

  return (
    <div
      className="admin-panel-backdrop"
      onClick={onClose}
      style={{ zIndex: 1100 }}
    >
      <div
        className="admin-panel admin-modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: "680px", width: "95vw" }}
      >
        <ScenarioModalHeader editingScenarioId={editingScenarioId} onClose={onClose} />

        <div
          className="admin-modal__body"
          style={{ overflowY: "auto", maxHeight: "80vh" }}
        >
          <form
            className="admin-modal__stack"
            onSubmit={(e) => void onSaveScenario(e)}
          >
            {/* Basic info */}
            <ScenarioBasicFields props={props} />

            {/* Match config */}
            <ScenarioMatchSection match={match} syncMatch={syncMatch} />

            {/* Planner config */}
            <ScenarioPlannerSection planner={planner} syncPlanner={syncPlanner} />

            {/* Execution config */}
            <ScenarioExecutionSection execution={execution} syncExecution={syncExecution} />

            {scenarioFormError ? (
              <div className="admin-panel__form-error">{scenarioFormError}</div>
            ) : null}

            <ScenarioFormActions
              editingScenarioId={editingScenarioId}
              scenarioFormLoading={scenarioFormLoading}
              onClose={onClose}
            />
          </form>
        </div>
      </div>
    </div>
  );
}

function ScenarioModalHeader({
  editingScenarioId,
  onClose,
}: Pick<AdminScenarioFormModalProps, "editingScenarioId" | "onClose">) {
  return (
    <div className="admin-panel__header">
      <span className="admin-panel__title">
        {editingScenarioId ? "Edit Scenario" : "New Scenario"}
      </span>
      <button
        type="button"
        className="icon-button"
        onClick={onClose}
        aria-label="Close"
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M5 5L15 15M15 5L5 15" />
        </svg>
      </button>
    </div>
  );
}

function ScenarioFormActions({
  editingScenarioId,
  scenarioFormLoading,
  onClose,
}: Pick<AdminScenarioFormModalProps, "editingScenarioId" | "scenarioFormLoading" | "onClose">) {
  return (
    <div className="admin-panel__form-actions">
      <button
        type="submit"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={scenarioFormLoading}
      >
        {scenarioFormLoading
          ? "Saving…"
          : editingScenarioId
            ? "Save Changes"
            : "Create Scenario"}
      </button>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onClose}
      >
        Cancel
      </button>
    </div>
  );
}

function ScenarioBasicFields({ props }: { props: AdminScenarioFormModalProps }) {
  return (
    <ScenarioBasicSection
      projects={props.projects}
      scenarioName={props.scenarioName}
      setScenarioName={props.setScenarioName}
      scenarioProjectId={props.scenarioProjectId}
      setScenarioProjectId={props.setScenarioProjectId}
      scenarioPriority={props.scenarioPriority}
      setScenarioPriority={props.setScenarioPriority}
      scenarioActive={props.scenarioActive}
      setScenarioActive={props.setScenarioActive}
      scenarioDescription={props.scenarioDescription}
      setScenarioDescription={props.setScenarioDescription}
    />
  );
}
