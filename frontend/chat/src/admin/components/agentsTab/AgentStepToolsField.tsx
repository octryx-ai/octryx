import { useId, useState } from "react";

import { stepToolsLabel } from "./agentWorkspaceModel";
import {
  filterToolCatalog,
  parseToolList,
  removeTool,
  splitByCatalog,
  toggleTool,
} from "./stepToolSelection";
import "./agentStepForm.css";

type AgentStepToolsFieldProps = {
  value: string;
  catalog: string[];
  onChange: (value: string) => void;
};

// Step tool restriction picked from the registered tool catalog. Saved IDs the
// catalog no longer lists stay selected and are marked; they are only removed
// on an explicit click. Nothing is ever added that was not picked.
export function AgentStepToolsField({ value, catalog, onChange }: AgentStepToolsFieldProps) {
  const fieldId = useId();
  const searchId = `${fieldId}-search`;
  const summaryId = `${fieldId}-summary`;
  const [query, setQuery] = useState("");
  const selected = parseToolList(value);
  const { unknown } = splitByCatalog(selected, catalog);
  const chosen = new Set(selected);
  const visible = filterToolCatalog(catalog, query);

  return (
    <fieldset className="agent-step-tools task-form__field task-form__field--full" aria-describedby={summaryId}>
      <legend className="admin-panel__form-label">Allowed tools</legend>
      <p id={summaryId} className="agent-step-tools__summary">
        {selected.length === 0
          ? stepToolsLabel([])
          : `${selected.length} selected. Only these tools can be used in this step; mode, workspace connectors and policy still apply.`}
      </p>
      {selected.length > 0 ? (
        <ul className="agent-step-tools__chips" aria-label="Selected tools">
          {selected.map((id) => {
            const missing = unknown.includes(id);
            return (
              <li key={id} className={`agent-step-tools__chip${missing ? " agent-step-tools__chip--unknown" : ""}`}>
                <span className="agent-step-tools__chip-name">{id}</span>
                {missing ? <span className="agent-step-tools__chip-note">Not in the current catalog</span> : null}
                <button
                  type="button"
                  className="agent-step-tools__chip-remove"
                  aria-label={`Remove tool ${id}`}
                  onClick={() => onChange(removeTool(value, id))}
                >
                  ✕
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {catalog.length === 0 ? (
        <p className="agent-step-tools__empty">
          The tool catalog is not available right now. Saved tools are kept as they are.
        </p>
      ) : (
        <>
          <label htmlFor={searchId} className="admin-panel__form-label">
            Find a tool
          </label>
          <input
            id={searchId}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="connector-field__input"
            placeholder={`Search ${catalog.length} registered tools`}
          />
          <div className="agent-step-tools__catalog" role="group" aria-label="Tool catalog">
            {visible.map((id) => (
              <label key={id} className="agents-form__check agent-step-tools__option">
                <input
                  type="checkbox"
                  checked={chosen.has(id)}
                  onChange={(event) => onChange(toggleTool(value, id, event.target.checked))}
                />
                <span className="agent-step-tools__option-name">{id}</span>
              </label>
            ))}
            {visible.length === 0 ? <p className="agent-step-tools__empty">No registered tool matches this search.</p> : null}
          </div>
        </>
      )}
    </fieldset>
  );
}
