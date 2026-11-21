// Admin scenarios tab: scenario profile list with how a scenario is chosen, plus the create/edit form modal.
import {
  type Dispatch,
  type FormEvent,
  type SetStateAction,
} from "react";
import { AdminScenarioFormModal } from "./AdminScenarioFormModal";
import { ScenarioCard, type ScenarioProfileRow } from "./AdminScenarioCard";
import { AreaPurpose } from "./workflowSurfaces/AreaPurpose";
import { WORKFLOWS_HOME } from "./workflowSurfaces/workflowAdministration";
import "./workflowSurfaces/scenarios.css";

type ProjectOptionRow = {
  id: string;
  name: string;
};

type AdminScenariosTabCtx = {
  scenarioProfiles: ScenarioProfileRow[];
  projects: ProjectOptionRow[];
  showScenarioForm: boolean;
  editingScenarioId: string | null;
  scenarioName: string;
  setScenarioName: Dispatch<SetStateAction<string>>;
  scenarioDescription: string;
  setScenarioDescription: Dispatch<SetStateAction<string>>;
  scenarioProjectId: string;
  setScenarioProjectId: Dispatch<SetStateAction<string>>;
  scenarioPriority: number;
  setScenarioPriority: Dispatch<SetStateAction<number>>;
  scenarioMatchConfig: string;
  setScenarioMatchConfig: Dispatch<SetStateAction<string>>;
  scenarioPlannerConfig: string;
  setScenarioPlannerConfig: Dispatch<SetStateAction<string>>;
  scenarioExecutionConfig: string;
  setScenarioExecutionConfig: Dispatch<SetStateAction<string>>;
  scenarioActive: boolean;
  setScenarioActive: Dispatch<SetStateAction<boolean>>;
  scenarioFormLoading: boolean;
  scenarioFormError: string | null;
  onOpenScenarioForm: (profile?: ScenarioProfileRow) => void;
  onCloseScenarioForm: () => void;
  onSaveScenario: (event: FormEvent) => void | Promise<void>;
  onDeleteScenario: (scenarioId: string, name: string) => void | Promise<void>;
};

type AdminScenariosTabProps = {
  ctx: Record<string, unknown>;
};

// The create/edit form, fed from the tab context.
function ScenarioFormFromCtx({ ctx }: { ctx: AdminScenariosTabCtx }) {
  const {
    projects,
    showScenarioForm,
    editingScenarioId,
    scenarioName,
    setScenarioName,
    scenarioDescription,
    setScenarioDescription,
    scenarioProjectId,
    setScenarioProjectId,
    scenarioPriority,
    setScenarioPriority,
    scenarioMatchConfig,
    setScenarioMatchConfig,
    scenarioPlannerConfig,
    setScenarioPlannerConfig,
    scenarioExecutionConfig,
    setScenarioExecutionConfig,
    scenarioActive,
    setScenarioActive,
    scenarioFormLoading,
    scenarioFormError,
    onCloseScenarioForm,
    onSaveScenario,
  } = ctx;
  return (
    <AdminScenarioFormModal
      show={showScenarioForm}
      editingScenarioId={editingScenarioId}
      projects={projects}
      scenarioName={scenarioName}
      setScenarioName={setScenarioName}
      scenarioProjectId={scenarioProjectId}
      setScenarioProjectId={setScenarioProjectId}
      scenarioPriority={scenarioPriority}
      setScenarioPriority={setScenarioPriority}
      scenarioActive={scenarioActive}
      setScenarioActive={setScenarioActive}
      scenarioDescription={scenarioDescription}
      setScenarioDescription={setScenarioDescription}
      scenarioMatchConfig={scenarioMatchConfig}
      setScenarioMatchConfig={setScenarioMatchConfig}
      scenarioPlannerConfig={scenarioPlannerConfig}
      setScenarioPlannerConfig={setScenarioPlannerConfig}
      scenarioExecutionConfig={scenarioExecutionConfig}
      setScenarioExecutionConfig={setScenarioExecutionConfig}
      scenarioFormError={scenarioFormError}
      scenarioFormLoading={scenarioFormLoading}
      onSaveScenario={onSaveScenario}
      onClose={onCloseScenarioForm}
    />
  );
}

type ScenarioListProps = Pick<AdminScenariosTabCtx, "scenarioProfiles" | "onOpenScenarioForm" | "onDeleteScenario"> & {
  projectNameById: Map<string, string>;
};

function ScenarioList({ scenarioProfiles, projectNameById, onOpenScenarioForm, onDeleteScenario }: ScenarioListProps) {
  return scenarioProfiles.length === 0 ? (
    <div className="admin-panel__empty-state">
      No scenario profiles yet. Add one to steer context assembly for a
      route.
    </div>
  ) : (
    <div className="task-list">
      {scenarioProfiles.map((profile) => (
        <ScenarioCard
          key={profile.id}
          profile={profile}
          projectNameById={projectNameById}
          onEdit={() => onOpenScenarioForm(profile)}
          onDelete={() => void onDeleteScenario(profile.id, profile.name)}
        />
      ))}
    </div>
  );
}

export function AdminScenariosTab({ ctx }: AdminScenariosTabProps) {
  const { scenarioProfiles, projects, onOpenScenarioForm, onDeleteScenario } = ctx as AdminScenariosTabCtx;

  const projectNameById = new Map(
    projects.map((project) => [project.id, project.name]),
  );
  const activeCount = scenarioProfiles.filter((p) => p.is_active).length;
  const projectScopedCount = scenarioProfiles.filter(
    (p) => p.project_id,
  ).length;

  return (
    <div className="scenarios-page">
      <AreaPurpose
        links={[
          { tab: "instructions", label: "Instructions" },
        ]}
        back={WORKFLOWS_HOME}
      />
      <div className="admin-panel__section-header">
        <span>
          Scenarios ({scenarioProfiles.length}) · {activeCount} active · {projectScopedCount} workspace-scoped ·{" "}
          {scenarioProfiles.length - projectScopedCount} global
        </span>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => onOpenScenarioForm()}
        >
          + New scenario
        </button>
      </div>
      <ol className="scenarios-page__steps">
        <li>A request arrives; its route reason and tool domains are determined from the turn context.</li>
        <li>Active scenarios whose route reasons and domains match are candidates.</li>
        <li>The highest priority wins; on a tie a workspace scenario beats a global one.</li>
        <li>Its context settings replace the defaults for that turn.</li>
      </ol>

      <ScenarioList scenarioProfiles={scenarioProfiles} projectNameById={projectNameById} onOpenScenarioForm={onOpenScenarioForm}
        onDeleteScenario={onDeleteScenario} />

      <ScenarioFormFromCtx ctx={ctx as AdminScenariosTabCtx} />
    </div>
  );
}
