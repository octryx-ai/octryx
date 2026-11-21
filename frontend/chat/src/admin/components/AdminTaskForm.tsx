import {
  TaskFormFooter,
  TaskFormNotes,
  TaskNameFields,
  TaskPathFields,
  TaskRunLimitFields,
} from "./AdminTaskFormParts";
import { taskFormView, useTaskFormSources, type AdminTaskFormProps } from "./adminTaskFormModel";
import { SidePanel } from "../../layout/SidePanel";
import "./adminSchedulers.css";

export function AdminTaskForm(props: AdminTaskFormProps) {
  const { showTaskForm, editingTask, onSaveTask, onCloseTaskForm } = props;
  const sources = useTaskFormSources(props);
  if (!showTaskForm) {
    return null;
  }
  const view = taskFormView(props, sources);
  const { guided } = sources;

  // Create and edit open in a side panel over the list; Cancel, then the primary action.
  return (
    <SidePanel
      title={editingTask ? `Edit ${editingTask.name}` : "New action"}
      onClose={onCloseTaskForm}
      testId="action-panel"
      footer={<TaskFormFooter props={props} sources={sources} view={view} />}
    >
    <form
      id="action-form"
      className="task-form task-form--panel"
      onSubmit={(event) => void onSaveTask(event, guided ? view.guidedSave : undefined)}
    >
      <div className="task-form__grid">
        <TaskNameFields props={props} />
        <TaskPathFields props={props} sources={sources} view={view} />
      </div>
      <TaskRunLimitFields props={props} guided={guided} />
      <TaskFormNotes props={props} sources={sources} view={view} />
    </form>
    </SidePanel>
  );
}
