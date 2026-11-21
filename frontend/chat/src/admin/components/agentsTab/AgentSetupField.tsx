import { useEffect, useState } from "react";

import {
  CEILING_OPTIONS,
  EXECUTION_MODE_OPTIONS,
  type AgentSetupFields,
  type ExecutionMode,
} from "./agentSetupFields";

type WorkflowOption = { key: string; title: string; capability: string };
type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type AgentSetupFieldProps = {
  value: AgentSetupFields;
  onChange: (next: AgentSetupFields) => void;
  readJson?: ReadJsonFn;
};

// Capability ceiling (radio cards), default workflow and how the agent runs. Agents are Global, so the
// workflow options are the published workflows offered without a Workspace.
export function AgentSetupField({ value, onChange, readJson }: AgentSetupFieldProps) {
  const [workflows, setWorkflows] = useState<WorkflowOption[]>([]);
  useEffect(() => {
    if (!readJson) return;
    void readJson<{ workflows?: WorkflowOption[] }>("/api/v1/effective-setup/options").then(
      (body) => setWorkflows(Array.isArray(body.workflows) ? body.workflows : []),
      () => setWorkflows([]),
    );
  }, [readJson]);
  const known = workflows.some((item) => item.key === value.defaultWorkflowKey);
  return (
    <>
      <fieldset className="admin-panel__field agents-form__field">
        <legend className="admin-panel__form-label">Capability ceiling</legend>
        <div className="aw-choice-grid">
          {CEILING_OPTIONS.map((option) => (
            <label key={option.value} className="admin-option-card">
              <input type="radio" name="agent-capability-ceiling" value={option.value}
                checked={value.capabilityCeiling === option.value}
                onChange={() => onChange({ ...value, capabilityCeiling: option.value })} />
              <span className="admin-option-card__body">
                <span className="admin-option-card__title">{option.title}</span>
                <span className="admin-option-card__desc">{option.description}</span>
              </span>
            </label>
          ))}
        </div>
        <span className="agents-form__help">A ceiling, not a grant: the workflow sets the class, Policies forbid.</span>
      </fieldset>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field">
          <span>Default workflow</span>
          <select value={value.defaultWorkflowKey}
            onChange={(event) => onChange({ ...value, defaultWorkflowKey: event.target.value })}>
            <option value="">Automatic</option>
            {value.defaultWorkflowKey && !known ? (
              <option value={value.defaultWorkflowKey}>{`${value.defaultWorkflowKey} (not published here)`}</option>
            ) : null}
            {workflows.map((item) => <option key={item.key} value={item.key}>{item.key}</option>)}
          </select>
        </label>
        <label className="admin-panel__field">
          <span>Runs as</span>
          <select value={value.executionMode}
            onChange={(event) => onChange({ ...value, executionMode: event.target.value as ExecutionMode })}>
            {EXECUTION_MODE_OPTIONS.map((option) => (
              <option key={option.value || "chat"} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      </div>
    </>
  );
}
