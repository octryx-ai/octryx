// Schedulers tab: the create and edit form in its side panel (name, description, schedule, next runs, action).
import { SidePanel } from "../../../layout/SidePanel";
import { SchedulerNextRunsPreview } from "./SchedulerNextRunsPreview";
import { SchedulerScheduleFields } from "./SchedulerScheduleFields";
import type { scheduleSubmitGate, SchedulePreviewState } from "./scheduleModel";
import type { AdminSchedulersTabCtx, TaskOptionRow } from "./schedulersTabTypes";

type SchedulerFormPanelProps = Pick<AdminSchedulersTabCtx,
  "tasks" | "editingScheduler" | "schedulerFormName" | "setSchedulerFormName" | "schedulerFormDesc" | "setSchedulerFormDesc"
  | "schedulerFormCron" | "setSchedulerFormCron" | "schedulerFormTaskId" | "setSchedulerFormTaskId" | "schedulerFormLoading"
  | "schedulerFormError" | "onCloseSchedulerForm" | "onSaveScheduler"> & {
  preview: SchedulePreviewState;
  retry: () => void;
  gate: ReturnType<typeof scheduleSubmitGate>;
  chosenAction: TaskOptionRow | undefined;
};

export function SchedulerFormPanel({
  tasks, editingScheduler, schedulerFormName, setSchedulerFormName, schedulerFormDesc, setSchedulerFormDesc,
  schedulerFormCron, setSchedulerFormCron, schedulerFormTaskId, setSchedulerFormTaskId, schedulerFormLoading,
  schedulerFormError, onCloseSchedulerForm, onSaveScheduler, preview, retry, gate, chosenAction,
}: SchedulerFormPanelProps) {
  return (
    <SidePanel
      title={editingScheduler ? `Edit ${editingScheduler.name}` : "New scheduler"}
      onClose={onCloseSchedulerForm}
      testId="scheduler-panel"
      footer={(
        <>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={onCloseSchedulerForm}
          >
            Cancel
          </button>
          <button
            type="submit"
            form="scheduler-form"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={schedulerFormLoading || !gate.canSubmit}
          >
            {schedulerFormLoading
              ? "Saving…"
              : editingScheduler
                ? "Save changes"
                : "Create and activate"}
          </button>
        </>
      )}
    >
    <SchedulerForm tasks={tasks} editingScheduler={editingScheduler} schedulerFormName={schedulerFormName}
      setSchedulerFormName={setSchedulerFormName} schedulerFormDesc={schedulerFormDesc} setSchedulerFormDesc={setSchedulerFormDesc}
      schedulerFormCron={schedulerFormCron} setSchedulerFormCron={setSchedulerFormCron} schedulerFormTaskId={schedulerFormTaskId}
      setSchedulerFormTaskId={setSchedulerFormTaskId} schedulerFormError={schedulerFormError} onSaveScheduler={onSaveScheduler}
      preview={preview} retry={retry} gate={gate} chosenAction={chosenAction} />
    </SidePanel>
  );
}

type SchedulerFormProps = Omit<SchedulerFormPanelProps, "schedulerFormLoading" | "onCloseSchedulerForm">;

// The form in the panel: the fields, what saving or creating does, and the error or the reason it cannot be saved yet.
function SchedulerForm({
  tasks, editingScheduler, schedulerFormName, setSchedulerFormName, schedulerFormDesc, setSchedulerFormDesc,
  schedulerFormCron, setSchedulerFormCron, schedulerFormTaskId, setSchedulerFormTaskId,
  schedulerFormError, onSaveScheduler, preview, retry, gate, chosenAction,
}: SchedulerFormProps) {
  return (
    <form
      id="scheduler-form"
      className="task-form task-form--panel"
      onSubmit={(event) => void onSaveScheduler(event, preview)}
    >
      <SchedulerFormFields tasks={tasks} editingScheduler={editingScheduler} schedulerFormName={schedulerFormName}
        setSchedulerFormName={setSchedulerFormName} schedulerFormDesc={schedulerFormDesc} setSchedulerFormDesc={setSchedulerFormDesc}
        schedulerFormCron={schedulerFormCron} setSchedulerFormCron={setSchedulerFormCron} schedulerFormTaskId={schedulerFormTaskId}
        setSchedulerFormTaskId={setSchedulerFormTaskId} preview={preview} retry={retry} gate={gate} />
      <p className="admin-panel__hint">
        {editingScheduler
          ? `Saving keeps this scheduler ${editingScheduler.is_active ? "active" : "paused"}; use Pause or Resume to change that.`
          : chosenAction
            ? `Creating activates this scheduler: it runs the action "${chosenAction.name}" at the times shown.`
            : "Creating activates this scheduler. Choose the action it runs."}
      </p>
      {schedulerFormError ? (
        <div className="admin-panel__form-error">{schedulerFormError}</div>
      ) : !gate.canSubmit && gate.blocker ? (
        <div className="admin-form-help">{gate.blocker}</div>
      ) : null}
    </form>
  );
}

type SchedulerFormFieldsProps = Omit<SchedulerFormProps, "schedulerFormError" | "onSaveScheduler" | "chosenAction">;

function SchedulerFormFields({
  tasks, editingScheduler, schedulerFormName, setSchedulerFormName, schedulerFormDesc, setSchedulerFormDesc,
  schedulerFormCron, setSchedulerFormCron, schedulerFormTaskId, setSchedulerFormTaskId, preview, retry, gate,
}: SchedulerFormFieldsProps) {
  return (
    <div className="task-form__grid">
      <div className="task-form__field task-form__field--full">
        <label className="admin-panel__form-label" htmlFor="scheduler-form-name">
          Scheduler name *
        </label>
        <input
          id="scheduler-form-name"
          value={schedulerFormName}
          onChange={(event) => setSchedulerFormName(event.target.value)}
          required
          className="connector-field__input"
        />
      </div>
      <div className="task-form__field task-form__field--full">
        <label className="admin-panel__form-label">Description</label>
        <input
          value={schedulerFormDesc}
          onChange={(event) => setSchedulerFormDesc(event.target.value)}
          className="connector-field__input"
        />
      </div>
      <SchedulerScheduleFields
        key={editingScheduler?.id ?? "new"}
        value={schedulerFormCron}
        onChange={setSchedulerFormCron}
      />
      <SchedulerNextRunsPreview preview={preview} gate={gate} onRetry={retry} />
      <div className="task-form__field task-form__field--full">
        <label className="admin-panel__form-label" htmlFor="scheduler-action">
          Action *
        </label>
        <select
          id="scheduler-action"
          value={schedulerFormTaskId}
          onChange={(event) => setSchedulerFormTaskId(event.target.value)}
          required
          className="connector-field__input"
        >
          <option value="">Select action…</option>
          {tasks.map((task) => (
            <option key={task.id} value={task.id}>
              {task.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
