import { useId } from "react";

import { toolUseDefaultNote, toolUseState, writeToolUse, type ToolUse } from "./stepToolSelection";

type AgentStepToolUseFieldProps = {
  config: string;
  allowedTools: string;
  onConfigChange: (config: string) => void;
};

// Whether the step must use one of its tools before it completes, stored as
// `tool_use` in the step configuration. Without a saved value the select shows
// the default (required exactly when the step lists tools); the key is written only when the user changes it.
export function AgentStepToolUseField({ config, allowedTools, onConfigChange }: AgentStepToolUseFieldProps) {
  const id = useId();
  const noteId = `${id}-note`;
  const state = toolUseState(config, allowedTools);
  const note = !state.writable
    ? "Fix the step configuration JSON to change this."
    : state.source === "default"
      ? toolUseDefaultNote(allowedTools)
      : state.source === "unrecognized"
        ? "The saved value is not recognised, so this step requires a tool. Pick one to replace it."
        : "";

  const change = (value: ToolUse) => {
    const next = writeToolUse(config, value);
    if (next !== null) onConfigChange(next);
  };

  return (
    <div className="task-form__field task-form__field--full">
      <label htmlFor={id} className="admin-panel__form-label">
        Tool use
      </label>
      <select
        id={id}
        value={state.value}
        onChange={(event) => change(event.target.value as ToolUse)}
        className="connector-field__input"
        disabled={!state.writable}
        aria-describedby={note ? noteId : undefined}
      >
        <option value="required">Must use one of its tools before the step completes</option>
        <option value="optional">May answer without tools</option>
      </select>
      {note ? (
        <span id={noteId} className="admin-panel__cell--muted">
          {note}
        </span>
      ) : null}
    </div>
  );
}
