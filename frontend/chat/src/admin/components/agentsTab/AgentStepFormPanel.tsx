import { useId, useState } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { AgentStepToolsField } from "./AgentStepToolsField";
import { AgentStepToolUseField } from "./AgentStepToolUseField";
import {
  normalizeToolCatalog,
  stepConfigIssue,
  stepConfigNeedsAttention,
} from "./stepToolSelection";
import "./agentStepForm.css";

const stepFormIds = (formId: string) => ({
  name: `${formId}-name`,
  type: `${formId}-type`,
  instructions: `${formId}-instructions`,
  successCriteria: `${formId}-success`,
  config: `${formId}-config`,
  configError: `${formId}-config-error`,
  form: `${formId}-form`,
});

type StepFormIds = ReturnType<typeof stepFormIds>;
type PartProps = { ctx: Record<string, unknown>; ids: StepFormIds };

type AgentStepFormPanelProps = {
  agentId: string;
  ctx: Record<string, unknown>;
};

export function AgentStepFormPanel({ agentId, ctx }: AgentStepFormPanelProps) {
  const {
    agentBuilderMeta, agentStepFormAllowedTools, agentStepFormConfig, agentStepFormEnabled, agentStepFormError,
    agentStepFormFor, closeAgentStepForm, editingAgentStep, handleSaveAgentStep,
    setAgentStepFormAllowedTools, setAgentStepFormConfig, setAgentStepFormEnabled,
  } = ctx as Record<string, any>;
  const formId = useId();
  const ids = stepFormIds(formId);
  const configText = typeof agentStepFormConfig === "string" ? agentStepFormConfig : "";
  const toolsText = typeof agentStepFormAllowedTools === "string" ? agentStepFormAllowedTools : "";
  // Opens on its own for an existing configuration; a JSON error keeps it open.
  const [configOpen, setConfigOpen] = useState(() => stepConfigNeedsAttention(configText));
  const toolCatalog = normalizeToolCatalog(agentBuilderMeta?.tool_options);

  if (agentStepFormFor !== agentId) return null;

  // Adding or editing a step opens a side panel over the dimmed agent page: the fields in the body,
  // Cancel and the primary action at the bottom right. The submit button sits outside the form, bound by `form`.
  return (
    <SidePanel
      title={editingAgentStep ? `Edit step: ${editingAgentStep.name}` : "New step"}
      onClose={closeAgentStepForm}
      testId="agent-step-panel"
      footer={<StepFormFooter ctx={ctx} ids={ids} />}
    >
    <form
      id={ids.form}
      className="task-form"
      onSubmit={(e) => void handleSaveAgentStep(e)}
    >
      <div className="task-form__grid" style={{ gap: "0.6rem" }}>
        <StepBasicsFields ctx={ctx} ids={ids} />
        <AgentStepToolsField value={toolsText} catalog={toolCatalog} onChange={setAgentStepFormAllowedTools} />
        <AgentStepToolUseField config={configText} allowedTools={toolsText} onConfigChange={setAgentStepFormConfig} />
        <StepConfigDetails ctx={ctx} ids={ids} configText={configText} configOpen={configOpen} setConfigOpen={setConfigOpen} />
        <div className="task-form__field task-form__field--full">
          <label className="admin-panel__form-label">
            <input
              type="checkbox"
              checked={agentStepFormEnabled}
              onChange={(e) => setAgentStepFormEnabled(e.target.checked)}
              style={{ marginRight: "0.5rem" }}
            />
            Step is enabled
          </label>
        </div>
      </div>
      {agentStepFormError ? (
        <div className="admin-panel__form-error">{agentStepFormError}</div>
      ) : null}
    </form>
    </SidePanel>
  );
}

function StepBasicsFields({ ctx, ids }: PartProps) {
  const {
    agentBuilderMeta, agentStepFormInstructions, agentStepFormName, agentStepFormSuccessCriteria, agentStepFormType,
    setAgentStepFormInstructions, setAgentStepFormName, setAgentStepFormSuccessCriteria, setAgentStepFormType,
  } = ctx as Record<string, any>;
  return (
    <>
    <div className="task-form__field">
      <label htmlFor={ids.name} className="admin-panel__form-label">Name</label>
      <input
        id={ids.name}
        value={agentStepFormName}
        onChange={(e) => setAgentStepFormName(e.target.value)}
        required
        className="connector-field__input"
      />
    </div>
    <div className="task-form__field">
      <label htmlFor={ids.type} className="admin-panel__form-label">Type</label>
      <select
        id={ids.type}
        value={agentStepFormType}
        onChange={(e) => setAgentStepFormType(e.target.value)}
        className="connector-field__input"
      >
        {(agentBuilderMeta?.step_type_options || []).map(
          (option: string) => (
            <option key={option} value={option}>
              {option}
            </option>
          ),
        )}
      </select>
    </div>
    <div className="task-form__field task-form__field--full">
      <label htmlFor={ids.instructions} className="admin-panel__form-label">Instructions</label>
      <textarea
        id={ids.instructions}
        value={agentStepFormInstructions}
        onChange={(e) => setAgentStepFormInstructions(e.target.value)}
        className="connector-field__input connector-field__input--textarea"
        rows={3}
      />
    </div>
    <div className="task-form__field task-form__field--full">
      <label htmlFor={ids.successCriteria} className="admin-panel__form-label">Success criteria</label>
      <textarea
        id={ids.successCriteria}
        value={agentStepFormSuccessCriteria}
        onChange={(e) => setAgentStepFormSuccessCriteria(e.target.value)}
        className="connector-field__input connector-field__input--textarea"
        rows={2}
      />
    </div>
    </>
  );
}

type ConfigProps = PartProps & { configText: string; configOpen: boolean; setConfigOpen: (open: boolean) => void };

function StepConfigDetails({ ctx, ids, configText, configOpen, setConfigOpen }: ConfigProps) {
  const { agentStepFormType, setAgentStepFormConfig } = ctx as Record<string, any>;
  const configIssue = stepConfigIssue(configText);
  return (
    <details
      className="agent-step-form__advanced task-form__field task-form__field--full"
      open={configOpen || Boolean(configIssue)}
      onToggle={(event) => setConfigOpen(event.currentTarget.open)}
    >
      <summary>Advanced: step configuration (JSON)</summary>
      <div className="agent-step-form__advanced-body">
        <label htmlFor={ids.config} className="admin-panel__form-label">
          Step configuration <span className="admin-panel__cell--muted">JSON</span>
        </label>
        <textarea
          id={ids.config}
          value={configText}
          onChange={(e) => setAgentStepFormConfig(e.target.value)}
          className="connector-field__input connector-field__input--textarea"
          rows={agentStepFormType === "tdd_cycle" ? 8 : 4}
          spellCheck={false}
          aria-invalid={configIssue ? true : undefined}
          aria-describedby={configIssue ? ids.configError : undefined}
          placeholder={
            agentStepFormType === "tdd_cycle"
              ? '{\n  "tdd_cycle_phases": ["write_tests", "make_green", "security_review", "refactor", "self_review"]\n}'
              : "{\n  \n}"
          }
        />
        {configIssue ? (
          <p id={ids.configError} className="agent-step-form__config-error" role="alert">
            {configIssue}
          </p>
        ) : null}
      </div>
    </details>
  );
}

function StepFormFooter({ ctx, ids }: PartProps) {
  const { agentStepFormLoading, closeAgentStepForm, editingAgentStep } = ctx as Record<string, any>;
  return (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={closeAgentStepForm}>
        Cancel
      </button>
      <button
        type="submit"
        form={ids.form}
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={agentStepFormLoading}
      >
        {agentStepFormLoading
          ? "Saving…"
          : editingAgentStep
            ? "Save step"
            : "Add step"}
      </button>
    </>
  );
}
