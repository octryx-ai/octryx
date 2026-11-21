import { useEffect, useMemo, useState } from "react";

import type {
  WorkspaceAssignmentControls,
  WorkspaceAssignmentControlsUpdatePayload,
  WorkspaceCapabilityBinding,
} from "../../../types/workspaceCompositionTypes";

type WorkspaceAssignmentControlsPanelProps = {
  controls: WorkspaceAssignmentControls;
  bindings: WorkspaceCapabilityBinding[];
  // Agents only; the runtime settings are Workspace → Models.
  view: "agents";
  isSaving: boolean;
  onSave: (patch: WorkspaceAssignmentControlsUpdatePayload) => Promise<unknown>;
};

type AssignmentMode = "all_installed" | "selected_only";

function normalizeMode(value: string): AssignmentMode {
  return value === "selected_only" ? "selected_only" : "all_installed";
}

function bindingLabel(binding: WorkspaceCapabilityBinding): string {
  return `${binding.display_name || binding.binding_key} (${binding.binding_key})`;
}

export function WorkspaceAssignmentControlsPanel({
  controls,
  bindings,
  view,
  isSaving,
  onSave,
}: WorkspaceAssignmentControlsPanelProps) {
  void view;
  const relevantBindings = useMemo(
    () =>
      bindings.filter(
        (binding) =>
          binding.capability_kind === "agent" &&
          binding.is_enabled &&
          binding.binding_status !== "hidden",
      ),
    [bindings],
  );
  const [agentMode, setAgentMode] = useState<AssignmentMode>(
    normalizeMode(controls.agent_assignment_mode),
  );
  const [defaultAgentKey, setDefaultAgentKey] = useState(
    controls.default_agent_binding_key || "",
  );

  useEffect(() => {
    setAgentMode(normalizeMode(controls.agent_assignment_mode));
    setDefaultAgentKey(controls.default_agent_binding_key || "");
  }, [controls]);

  const handleSave = async () => {
    await onSave({ agent_assignment_mode: agentMode, default_agent_binding_key: defaultAgentKey });
  };

  return (
    <section className="connector-card connector-card--configured">
      <AssignmentHeader agentMode={agentMode} />
      <div className="task-item__runs" style={{ paddingTop: 0 }}>
        <AssignmentFields agentMode={agentMode} setAgentMode={setAgentMode} defaultAgentKey={defaultAgentKey}
          setDefaultAgentKey={setDefaultAgentKey} relevantBindings={relevantBindings} />
        <div className="admin-inline-actions" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            onClick={() => void handleSave()}
            disabled={isSaving}
          >
            {isSaving ? "Saving…" : "Save assignment"}
          </button>
          <span className="task-item__badge task-item__badge--secondary">
            enabled choices: {relevantBindings.length}
          </span>
        </div>
      </div>
    </section>
  );
}

function AssignmentHeader({ agentMode }: { agentMode: AssignmentMode }) {
  return (
    <div className="connector-card__header">
      <div className="connector-card__info">
        <div className="connector-card__name-row">
          <div className="connector-card__name">
            Agent assignment
          </div>
          <span className="connector-card__meta-badge">
            {agentMode}
          </span>
        </div>
        <div className="connector-card__meta">
          Controls whether this Workspace can use every installed agent or only selected enabled agents.
        </div>
      </div>
    </div>
  );
}

// The agent mode and the default agent among the enabled, visible agents.
function AssignmentFields({ agentMode, setAgentMode, defaultAgentKey, setDefaultAgentKey, relevantBindings }: {
  agentMode: AssignmentMode;
  setAgentMode: (mode: AssignmentMode) => void;
  defaultAgentKey: string;
  setDefaultAgentKey: (key: string) => void;
  relevantBindings: WorkspaceCapabilityBinding[];
}) {
  return (
    <div className="admin-form-grid admin-form-grid--dual">
      <label className="admin-form-field">
        <span>Agent mode</span>
        <select value={agentMode} onChange={(event) => setAgentMode(normalizeMode(event.target.value))}>
          <option value="all_installed">All installed</option>
          <option value="selected_only">Selected only</option>
        </select>
      </label>
      <label className="admin-form-field">
        <span>Default agent</span>
        <select value={defaultAgentKey} onChange={(event) => setDefaultAgentKey(event.target.value)}>
          <option value="">No explicit default</option>
          {relevantBindings.map((binding) => (
            <option key={binding.binding_key} value={binding.binding_key}>
              {bindingLabel(binding)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
