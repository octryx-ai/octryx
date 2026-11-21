import { useId } from "react";

import { isToolSurface, stepsNeedingTools, TOOL_SURFACE_OPTIONS, type ToolSurface } from "./agentToolSurface";
import type { PanelAgentStep } from "../../types/adminPanelTypes.agents";

type AgentToolSurfaceFieldProps = {
  value: string;
  onChange: (value: ToolSurface) => void;
  // Saved steps of the agent being edited; empty for a new agent.
  steps: PanelAgentStep[];
};

// Tools: policy-governed (default) or none. The choice is the author's; an unknown saved value is
// shown as such with nothing preselected. Steps that need tools are named, never changed here.
export function AgentToolSurfaceField({ value, onChange, steps }: AgentToolSurfaceFieldProps) {
  const name = useId();
  const known = isToolSurface(value);
  const conflicts = value === "none" ? stepsNeedingTools(steps) : [];
  return (
    <fieldset className="agents-form__field agents-form__choices">
      <legend className="admin-panel__form-label">Tools</legend>
      {TOOL_SURFACE_OPTIONS.map((option) => (
        <label key={option.value} className="agents-form__check">
          <input type="radio" name={name} value={option.value} checked={value === option.value} onChange={() => onChange(option.value)} />
          <span>
            {option.label}
            <span className="agents-form__help">{option.help}</span>
          </span>
        </label>
      ))}
      {!known ? (
        <div className="admin-panel__form-error" role="status">
          The saved tool setting “{value || "empty"}” is not recognised, so neither option is selected. Choose one before saving.
        </div>
      ) : null}
      {conflicts.length ? (
        <div className="admin-panel__form-error" role="status">
          These steps list tools or require tool use: {conflicts.join(", ")}. The server refuses No tools while they do. Remove
          their tools or set them to answer without tools in the Steps section first; nothing is changed for you.
        </div>
      ) : null}
    </fieldset>
  );
}
