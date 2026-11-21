// Parts of the Action step editor form: header, name and type, connector, instructions and runtime.
import type { Dispatch, FormEvent, MutableRefObject, SetStateAction } from "react";
import type { PanelAgentRow, PanelTaskStepRow } from "./taskTypes";

export type AdminTaskStepFormProps = {
  taskId: string;
  editingStep: PanelTaskStepRow | null;
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
  onSubmitStep: (event: FormEvent, taskId: string) => Promise<void>;
  onCancel: () => void;
};

export function StepFormHeader({
  editingStep,
  onCancel,
}: Pick<AdminTaskStepFormProps, "editingStep" | "onCancel">) {
  return (
    <div className="step-form__header">
      <div>
        <div className="step-form__eyebrow">
          {editingStep ? "Edit Step" : "New Step"}
        </div>
        <div className="step-form__title">
          {editingStep?.name || "Configure action step"}
        </div>
      </div>
      <button
        type="button"
        className="admin-panel__icon-btn"
        aria-label="Close step editor"
        onClick={onCancel}
      >
        ✕
      </button>
    </div>
  );
}

export function StepNameAndTypeFields({
  props,
  firstFieldRef,
}: {
  props: AdminTaskStepFormProps;
  firstFieldRef: MutableRefObject<HTMLInputElement | null>;
}) {
  return (
    <>
      <div className="task-form__field">
        <label className="admin-panel__form-label">Step name</label>
        <input
          ref={firstFieldRef}
          value={props.stepFormName}
          onChange={(event) => props.setStepFormName(event.target.value)}
          required
          className="connector-field__input"
        />
      </div>

      <div className="task-form__field">
        <label className="admin-panel__form-label">Type</label>
        <select
          value={props.stepFormType}
          onChange={(event) => props.setStepFormType(event.target.value)}
          className="connector-field__input"
        >
          <option value="connector_fetch">Connector Fetch</option>
          <option value="analysis">Analysis</option>
          <option value="sub_agent_spawn">Sub-Agent Spawn</option>
          <option value="verification">Verification</option>
          <option value="condition">Condition</option>
          <option value="output">Output</option>
        </select>
      </div>
    </>
  );
}

export function StepConnectorFields({ props }: { props: AdminTaskStepFormProps }) {
  return (
    <>
      <div className="task-form__field">
        <label className="admin-panel__form-label">
          Connector{" "}
          <span
            className="admin-panel__cell--muted"
            style={{ fontWeight: 400 }}
          >
            (optional)
          </span>
        </label>
        <select
          value={props.stepFormConnector}
          onChange={(event) => props.setStepFormConnector(event.target.value)}
          className="connector-field__input"
        >
          <option value="">None</option>
          <option value="jira">Jira</option>
          <option value="confluence">Confluence</option>
          <option value="bitbucket">Bitbucket</option>
          <option value="kubernetes">Kubernetes</option>
          <option value="grafana">Grafana</option>
          <option value="prometheus">Prometheus</option>
          <option value="loki">Loki</option>
        </select>
      </div>

      {props.stepFormConnector ? (
        <div className="task-form__field">
          <label className="admin-panel__form-label">Action</label>
          <input
            value={props.stepFormConnectorAction}
            onChange={(event) =>
              props.setStepFormConnectorAction(event.target.value)
            }
            placeholder="e.g. search_jira_tickets"
            className="connector-field__input"
          />
        </div>
      ) : null}
    </>
  );
}

export function StepInstructionsAndRuntimeFields({ props }: { props: AdminTaskStepFormProps }) {
  return (
    <>
      <div className="task-form__field task-form__field--full">
        <label className="admin-panel__form-label">Instructions</label>
        <textarea
          value={props.stepFormInstructions}
          onChange={(event) => props.setStepFormInstructions(event.target.value)}
          className="connector-field__input connector-field__input--textarea"
          rows={3}
          placeholder="What should this step do?"
        />
      </div>
    </>
  );
}

export function StepFormActions({
  editingStep,
  stepFormLoading,
  onCancel,
}: Pick<AdminTaskStepFormProps, "editingStep" | "stepFormLoading" | "onCancel">) {
  return (
    <div
      className="admin-panel__form-actions"
      style={{ marginTop: "0.5rem" }}
    >
      <button
        type="submit"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={stepFormLoading}
      >
        {stepFormLoading ? "Saving…" : editingStep ? "Save Step" : "Add Step"}
      </button>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onCancel}
      >
        Cancel
      </button>
    </div>
  );
}
