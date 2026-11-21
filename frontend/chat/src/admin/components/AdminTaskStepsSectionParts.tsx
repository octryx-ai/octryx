// Parts of an Action's expanded steps section: the dependency graph, the step editor and its modal.
import type { Dispatch, FormEvent, SetStateAction } from "react";
import { AdminTaskDependencyGraph } from "./AdminTaskDependencyGraph";
import { AdminTaskStepForm } from "./AdminTaskStepForm";
import { AdminTaskStepList } from "./AdminTaskStepList";
import type {
  PanelAgentRow,
  PanelTaskDependencyStateRow,
  PanelTaskRow,
  PanelTaskStepRow,
} from "./taskTypes";

export type AdminTaskStepsSectionProps = {
  isExpanded: boolean;
  task: PanelTaskRow;
  taskDependencies: Record<string, PanelTaskDependencyStateRow>;
  onDeleteTaskDependency: (
    taskId: string,
    dependencyId: string,
  ) => Promise<void>;
  taskDependencyTarget: Record<string, string>;
  setTaskDependencyTarget: Dispatch<SetStateAction<Record<string, string>>>;
  taskDependencyCondition: Record<string, string>;
  setTaskDependencyCondition: Dispatch<SetStateAction<Record<string, string>>>;
  onAddTaskDependency: (taskId: string) => Promise<void>;
  taskSteps: Record<string, PanelTaskStepRow[]>;
  onExpandSteps: (taskId: string) => Promise<void>;
  onOpenStepForm: (taskId: string, step?: PanelTaskStepRow) => void;
  showStepForm: string | null;
  setShowStepForm: Dispatch<SetStateAction<string | null>>;
  editingStep: PanelTaskStepRow | null;
  setEditingStep: Dispatch<SetStateAction<PanelTaskStepRow | null>>;
  stepFormName: string;
  setStepFormName: Dispatch<SetStateAction<string>>;
  stepFormType: string;
  setStepFormType: Dispatch<SetStateAction<string>>;
  stepFormConnector: string;
  setStepFormConnector: Dispatch<SetStateAction<string>>;
  stepFormConnectorAction: string;
  setStepFormConnectorAction: Dispatch<SetStateAction<string>>;
  stepFormInstructions: string;
  setStepFormInstructions: Dispatch<SetStateAction<string>>;
  stepFormAgentId: string;
  setStepFormAgentId: Dispatch<SetStateAction<string>>;
  panelAgents: PanelAgentRow[];
  stepFormContextFields: string;
  setStepFormContextFields: Dispatch<SetStateAction<string>>;
  stepFormConnectorParams: string;
  setStepFormConnectorParams: Dispatch<SetStateAction<string>>;
  stepFormMaxFix: number;
  setStepFormMaxFix: Dispatch<SetStateAction<number>>;
  stepFormTimeout: number;
  setStepFormTimeout: Dispatch<SetStateAction<number>>;
  stepFormError: string | null;
  stepFormLoading: boolean;
  onSaveStep: (event: FormEvent, taskId: string) => Promise<void>;
  onMoveStep: (
    taskId: string,
    stepId: string,
    direction: "up" | "down",
  ) => Promise<void>;
  onDeleteStep: (taskId: string, stepId: string) => Promise<void>;
};

export function TaskDependencySection({ props }: { props: AdminTaskStepsSectionProps }) {
  const { task, setTaskDependencyTarget, setTaskDependencyCondition } = props;
  return (
    <AdminTaskDependencyGraph
      dependencyState={props.taskDependencies[task.id]}
      dependencyTarget={props.taskDependencyTarget[task.id] || ""}
      dependencyCondition={props.taskDependencyCondition[task.id] || "success"}
      onDependencyTargetChange={(value) =>
        setTaskDependencyTarget((previous) => ({
          ...previous,
          [task.id]: value,
        }))
      }
      onDependencyConditionChange={(value) =>
        setTaskDependencyCondition((previous) => ({
          ...previous,
          [task.id]: value,
        }))
      }
      onAddDependency={() => void props.onAddTaskDependency(task.id)}
      onDeleteDependency={(dependencyId) =>
        void props.onDeleteTaskDependency(task.id, dependencyId)
      }
    />
  );
}

function StepFormModal({ props }: { props: AdminTaskStepsSectionProps }) {
  const closeStepForm = () => {
    props.setShowStepForm(null);
    props.setEditingStep(null);
  };
  return (
    <div className="step-form-modal" role="dialog" aria-modal="true">
      <button
        type="button"
        className="step-form-modal__backdrop"
        aria-label="Close step editor"
        onClick={closeStepForm}
      />
      <div className="step-form-modal__panel">
        <AdminTaskStepForm
          taskId={props.task.id}
          editingStep={props.editingStep}
          stepFormName={props.stepFormName}
          setStepFormName={props.setStepFormName}
          stepFormType={props.stepFormType}
          setStepFormType={props.setStepFormType}
          stepFormConnector={props.stepFormConnector}
          setStepFormConnector={props.setStepFormConnector}
          stepFormConnectorAction={props.stepFormConnectorAction}
          setStepFormConnectorAction={props.setStepFormConnectorAction}
          stepFormInstructions={props.stepFormInstructions}
          setStepFormInstructions={props.setStepFormInstructions}
          stepFormAgentId={props.stepFormAgentId}
          setStepFormAgentId={props.setStepFormAgentId}
          panelAgents={props.panelAgents}
          stepFormContextFields={props.stepFormContextFields}
          setStepFormContextFields={props.setStepFormContextFields}
          stepFormConnectorParams={props.stepFormConnectorParams}
          setStepFormConnectorParams={props.setStepFormConnectorParams}
          stepFormMaxFix={props.stepFormMaxFix}
          setStepFormMaxFix={props.setStepFormMaxFix}
          stepFormTimeout={props.stepFormTimeout}
          setStepFormTimeout={props.setStepFormTimeout}
          stepFormError={props.stepFormError}
          stepFormLoading={props.stepFormLoading}
          onSubmitStep={props.onSaveStep}
          onCancel={closeStepForm}
        />
      </div>
    </div>
  );
}

export function StepsEditor({
  props,
  steps,
}: {
  props: AdminTaskStepsSectionProps;
  steps: PanelTaskStepRow[];
}) {
  const { task } = props;
  return (
    <>
      <div className="task-item__runs-header">
        <span
          style={{
            fontWeight: 600,
            fontSize: "var(--ds-text-sm)",
            color: "var(--muted-strong)",
          }}
        >
          Steps ({steps.length || task.step_count || 0})
        </span>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          style={{ fontSize: "var(--ds-text-xs)" }}
          onClick={() => {
            void props.onExpandSteps(task.id);
            props.onOpenStepForm(task.id);
          }}
        >
          + Add Step
        </button>
      </div>

      <div className="steps-list">
        {props.showStepForm === task.id ? <StepFormModal props={props} /> : null}

        <AdminTaskStepList
          taskId={task.id}
          steps={steps}
          panelAgents={props.panelAgents}
          onMoveStep={props.onMoveStep}
          onOpenStepForm={props.onOpenStepForm}
          onDeleteStep={props.onDeleteStep}
        />
      </div>
    </>
  );
}
