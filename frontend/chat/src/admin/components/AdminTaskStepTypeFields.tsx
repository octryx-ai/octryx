// Step editor fields that depend on the step type: agent, context fields, connector params, fix attempts, timeout.
import type { Dispatch, SetStateAction } from "react";
import type { PanelAgentRow } from "./taskTypes";

type AdminTaskStepTypeFieldsProps = {
  stepFormType: string;
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
};

function StepAgentField({ stepFormAgentId, setStepFormAgentId, panelAgents }: Pick<AdminTaskStepTypeFieldsProps, "stepFormAgentId" | "setStepFormAgentId" | "panelAgents">) {
  return (
    <div className="task-form__field">
      <label className="admin-panel__form-label">Agent</label>
      <select
        value={stepFormAgentId}
        onChange={(event) => setStepFormAgentId(event.target.value)}
        className="connector-field__input"
      >
        <option value="">Use action-level agent</option>
        <option value="__none__">No agent (suppress)</option>
        {panelAgents.map((agent) => (
          <option key={agent.id} value={agent.id}>
            {agent.name}
          </option>
        ))}
      </select>
      <div
        style={{
          fontSize: "var(--ds-text-2xs)",
          color: "var(--muted)",
          marginTop: "0.2rem",
        }}
      >
        "Action-level" uses the agent configured on the action itself.
      </div>
    </div>
  );
}

function StepContextField({ stepFormContextFields, setStepFormContextFields }: Pick<AdminTaskStepTypeFieldsProps, "stepFormContextFields" | "setStepFormContextFields">) {
  return (
    <div className="task-form__field task-form__field--full">
      <label className="admin-panel__form-label">
        Context fields{" "}
        <span style={{ fontWeight: 400, color: "var(--muted)" }}>
          from previous steps
        </span>
      </label>
      <input
        value={stepFormContextFields}
        onChange={(event) => setStepFormContextFields(event.target.value)}
        placeholder="steps.1.output.new_items, steps.2.output.response"
        className="connector-field__input"
      />
      <div
        style={{
          fontSize: "var(--ds-text-2xs)",
          color: "var(--muted)",
          marginTop: "0.2rem",
        }}
      >
        Comma-separated dot-paths injected into the agent prompt.
      </div>
    </div>
  );
}

function StepConnectorParamsField({ stepFormConnectorParams, setStepFormConnectorParams }: Pick<AdminTaskStepTypeFieldsProps, "stepFormConnectorParams" | "setStepFormConnectorParams">) {
  return (
    <div className="task-form__field task-form__field--full">
      <label className="admin-panel__form-label">
        Connector params{" "}
        <span style={{ fontWeight: 400, color: "var(--muted)" }}>
          JSON
        </span>
      </label>
      <textarea
        value={stepFormConnectorParams}
        onChange={(event) =>
          setStepFormConnectorParams(event.target.value)
        }
        className="connector-field__input connector-field__input--textarea"
        rows={10}
        spellCheck={false}
        placeholder={
          '{\n  "jql": "labels = \\"otto\\" AND status = \\"Open\\"",\n  "limit": 10\n}'
        }
      />
    </div>
  );
}

function StepMaxFixField({ stepFormMaxFix, setStepFormMaxFix }: Pick<AdminTaskStepTypeFieldsProps, "stepFormMaxFix" | "setStepFormMaxFix">) {
  return (
    <div className="task-form__field">
      <label className="admin-panel__form-label">Max fix attempts</label>
      <input
        type="number"
        min={0}
        max={5}
        value={stepFormMaxFix}
        onChange={(event) =>
          setStepFormMaxFix(Number(event.target.value))
        }
        className="connector-field__input"
      />
    </div>
  );
}

function StepTimeoutField({ stepFormTimeout, setStepFormTimeout }: Pick<AdminTaskStepTypeFieldsProps, "stepFormTimeout" | "setStepFormTimeout">) {
  return (
    <div className="task-form__field">
      <label className="admin-panel__form-label">Timeout (s)</label>
      <input
        type="number"
        min={30}
        max={3600}
        value={stepFormTimeout}
        onChange={(event) =>
          setStepFormTimeout(Number(event.target.value))
        }
        className="connector-field__input"
      />
    </div>
  );
}

export function AdminTaskStepTypeFields(props: AdminTaskStepTypeFieldsProps) {
  const { stepFormType } = props;
  return (
    <>
      {stepFormType === "sub_agent_spawn" ||
      stepFormType === "analysis" ||
      stepFormType === "verification" ? <StepAgentField {...props} /> : null}

      {stepFormType !== "connector_fetch" ? <StepContextField {...props} /> : null}

      {stepFormType === "connector_fetch" || stepFormType === "output" ? <StepConnectorParamsField {...props} /> : null}

      {stepFormType === "verification" ? <StepMaxFixField {...props} /> : null}

      {stepFormType === "sub_agent_spawn" ? <StepTimeoutField {...props} /> : null}
    </>
  );
}
