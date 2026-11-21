// Parts of the Action side panel form: footer, name fields, the guided fields (or why an Action is not guided), run
// limit and notes.
import { ActionGuidedFields } from "./automation/ActionGuidedFields";
import { guidedBindingText, offersConversion } from "./automation/actionDispatchBinding";
import { deferredInstructionNote } from "./automation/actionGuidedExecution";
import {
  chooseTaskWorkspace,
  setTaskConfigKey,
  workspaceLabel,
  type AdminTaskFormProps,
  type TaskFormSources,
  type TaskFormView,
} from "./adminTaskFormModel";

type PartProps = { props: AdminTaskFormProps; sources: TaskFormSources; view: TaskFormView };

export function TaskFormFooter({ props, sources, view }: PartProps) {
  const { editingTask, taskFormLoading, onCloseTaskForm } = props;
  const { guided } = sources;
  const { submission } = view;
  return (
    <>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onCloseTaskForm}
      >
        Cancel
      </button>
      <button
        type="submit"
        form="action-form"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={taskFormLoading || (guided && !submission.canSubmit)}
      >
        {taskFormLoading
          ? "Saving…"
          : editingTask
            ? "Save changes"
            : "Create action"}
      </button>
    </>
  );
}

export function TaskNameFields({ props }: Pick<PartProps, "props">) {
  const { taskFormName, setTaskFormName, taskFormDesc, setTaskFormDesc } = props;
  return (
    <>
      <div className="task-form__field task-form__field--full">
        <label className="admin-panel__form-label">Action name *</label>
        <input
          value={taskFormName}
          onChange={(event) => setTaskFormName(event.target.value)}
          required
          placeholder="e.g. Nightly Jira Sync"
          className="connector-field__input"
        />
      </div>
      <div className="task-form__field task-form__field--full">
        <label className="admin-panel__form-label">Description</label>
        <input
          value={taskFormDesc}
          onChange={(event) => setTaskFormDesc(event.target.value)}
          placeholder="What does this action do?"
          className="connector-field__input"
        />
      </div>
    </>
  );
}

export function TaskPathFields({ props, sources, view }: PartProps) {
  const { editingTask, projects = [] } = props;
  const { guided, path } = sources;
  return guided ? (
    <GuidedTaskFields props={props} sources={sources} view={view} />
  ) : editingTask && path.kind === "advanced" ? (
    // An Action the guided form does not represent keeps its type, run mode, agent and workspace; only its name,
    // description, run limit and raw configuration are edited here.
    <>
      <p className="action-guided__unguided task-form__field--full">{path.reason}</p>
      <div className="task-form__field task-form__field--full">
        <span className="admin-panel__form-label">Workspace</span>
        <div className="action-guided__readonly">
          {workspaceLabel(projects, editingTask.project_id)}{" "}
          <span className="admin-panel__cell--muted">(an action keeps its workspace)</span>
        </div>
      </div>
    </>
  ) : null;
}

function GuidedTaskFields({ props, sources, view }: PartProps) {
  const { editingTask, projects = [], taskFormAgentDefId, setTaskFormAgentDefId } = props;
  const { catalog, retryExecution, convertBinding, setConvertBinding } = sources;
  const { isNew, activeWorkspaces, workspaceId, agents, agent, agentAvailable, agentMode, execution, instruction, config } = view;
  return (
    <div className="task-form__field task-form__field--full">
      <ActionGuidedFields
        isNew={isNew}
        workspaces={activeWorkspaces}
        workspaceId={workspaceId}
        workspaceLabel={workspaceLabel(projects, editingTask?.project_id)}
        onWorkspace={(nextWorkspace) => chooseTaskWorkspace(props, agent, nextWorkspace)}
        agents={agents}
        agentId={taskFormAgentDefId}
        agent={agent}
        agentAvailable={agentAvailable}
        onAgent={setTaskFormAgentDefId}
        modeLabel={catalog.modes.find((mode) => mode.key === agentMode)?.name || agentMode}
        execution={execution}
        onRetryExecution={retryExecution}
        instructionNote={instruction ? deferredInstructionNote(instruction) : null}
        config={config}
        onPrompt={(prompt) => setTaskConfigKey(props, "prompt", prompt === "" ? undefined : prompt)}
        onCapability={(capability) => setTaskConfigKey(props, "capability_class", capability)}
        bindingText={guidedBindingText(editingTask)}
        offerConversion={offersConversion(editingTask)}
        convertBinding={convertBinding}
        onConvertBinding={setConvertBinding}
      />
    </div>
  );
}

export function TaskRunLimitFields({ props, guided }: Pick<PartProps, "props"> & { guided: boolean }) {
  const { taskFormMaxIterations, setTaskFormMaxIterations, taskFormConfig, setTaskFormConfig } = props;
  return (
    <details className="action-guided__advanced" open={!guided}>
      <summary>{guided ? "Advanced: run limit and raw configuration" : "Run limit and raw configuration"}</summary>
      <div className="task-form__grid">
        <div className="task-form__field">
          <label className="admin-panel__form-label">
            Max iterations{" "}
            <span className="admin-panel__cell--muted">(default: 32)</span>
          </label>
          <input
            type="number"
            min={1}
            max={200}
            value={taskFormMaxIterations}
            onChange={(event) =>
              setTaskFormMaxIterations(
                event.target.value === "" ? "" : Number(event.target.value),
              )
            }
            className="connector-field__input"
          />
        </div>
        <div className="task-form__field task-form__field--full">
          <label className="admin-panel__form-label" htmlFor="task-form-config">
            Config (JSON)
          </label>
          <textarea
            id="task-form-config"
            value={taskFormConfig}
            onChange={(event) => setTaskFormConfig(event.target.value)}
            className="connector-field__input connector-field__input--textarea"
            rows={5}
            spellCheck={false}
          />
        </div>
      </div>
    </details>
  );
}

export function TaskFormNotes({ props, sources, view }: PartProps) {
  const { editingTask, taskFormError } = props;
  const { guided } = sources;
  const { submission } = view;
  return (
    <>
      <p className="admin-panel__cell--muted">
        {editingTask
          ? "Saving keeps this action's current state (active or paused) and any schedule it already has."
          : "A new action is created active, without a schedule of its own. Creating it does not start a run; a scheduler or Execute does."}
      </p>
      {taskFormError ? (
        <div className="admin-panel__form-error">{taskFormError}</div>
      ) : guided && !submission.canSubmit && submission.blocker ? (
        <div className="admin-form-help" data-testid="action-guided-blocker">
          {submission.blocker}
        </div>
      ) : null}
    </>
  );
}
