import { useState } from "react";

import { ActionMenu } from "../../admin/components/workflowSurfaces/ActionMenu";
import { actionReady } from "./workflowRunRequests";
import { type RunAction, type RunActionValue } from "./workflowRunTypes";

type RunActionControlsProps = {
  actions: RunAction[];
  primary: RunAction | null;
  inputs: Record<string, number | string>;
  setInput: (key: string, value: number | string) => void;
  valueOf: (action: RunAction) => RunActionValue;
  busy: boolean;
  onChoose: (action: RunAction) => void;
  // The run's name for the ⋯ menu ("More actions for Login fix").
  objectName: string;
};

function ActionInput({ action, inputs, setInput }: Pick<RunActionControlsProps, "inputs" | "setInput"> & { action: RunAction }) {
  if (action.input?.kind === "number") {
    return (
      <label className="workflow-run-banner__input">
        <span>{action.input.label}</span>
        <input
          className="admin-panel__input"
          type="number"
          min={action.input.min}
          max={action.input.max}
          value={inputs[action.key] ?? action.input.default}
          onChange={(event) => setInput(action.key, Number(event.target.value))}
        />
      </label>
    );
  }
  if (action.input?.kind === "text") {
    const limit = action.input.max_length ?? (action.input.name === "branch" ? 200 : 500);
    if (limit > 500) {
      // The product owner's answers to the agent (ticket delivery): several lines, up to the server's limit.
      return (
        <label className="workflow-run-banner__input workflow-run-banner__input--text">
          <span>{action.input.label}</span>
          <textarea
            className="admin-panel__input"
            rows={6}
            maxLength={limit}
            required={action.input.required}
            value={String(inputs[action.key] ?? action.input.default)}
            onChange={(event) => setInput(action.key, event.target.value)}
          />
        </label>
      );
    }
    return (
      <label className="workflow-run-banner__input workflow-run-banner__input--text">
        <span>{action.input.label}</span>
        <input
          className="admin-panel__input"
          type="text"
          maxLength={limit}
          required={action.input.required}
          value={String(inputs[action.key] ?? action.input.default)}
          onChange={(event) => setInput(action.key, event.target.value)}
        />
      </label>
    );
  }
  if (action.input?.kind === "runtime_target") {
    return (
      <label className="workflow-run-banner__input workflow-run-banner__input--select">
        <span>{action.input.label}</span>
        <select
          className="admin-panel__input"
          value={String(inputs[action.key] ?? action.input.default)}
          onChange={(event) => setInput(action.key, event.target.value)}
        >
          {action.input.options.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    );
  }
  return null;
}

// The run's actions inside the bar's details (product inventory): the next action is the one primary
// button, the others neutral; destructive ones sit in a ⋯ menu and show their field (a reason) only once chosen.
export function RunActionControls({ actions, primary, inputs, setInput, valueOf, busy, onChoose, objectName }: RunActionControlsProps) {
  const [chosenDanger, setChosenDanger] = useState<string | null>(null);
  const plain = actions.filter((action) => action.tone !== "danger");
  const danger = actions.filter((action) => action.tone === "danger");
  const pending = danger.find((action) => action.key === chosenDanger) ?? null;
  if (!actions.length) return null;
  return (
    <div className="workflow-run-banner__actions" role="group" aria-label="Run actions">
      {plain.map((action) => (
        <span key={action.key} className="workflow-run-banner__action">
          <ActionInput action={action} inputs={inputs} setInput={setInput} />
          <button
            type="button"
            className={`work-area__button${action === primary ? " work-area__button--primary" : ""}`}
            disabled={busy || !actionReady(action, valueOf(action))}
            onClick={() => onChoose(action)}
          >
            {action.label}
          </button>
        </span>
      ))}
      {danger.length ? (
        <ActionMenu
          row={{ objectName }}
          items={danger.map((action) => ({
            label: action.label,
            danger: true,
            disabled: busy,
            onSelect: () => (action.input ? setChosenDanger(action.key) : onChoose(action)),
          }))}
        />
      ) : null}
      {pending ? (
        <span className="workflow-run-banner__action workflow-run-banner__pending" data-testid="workflow-run-danger-confirm">
          <ActionInput action={pending} inputs={inputs} setInput={setInput} />
          <button
            type="button"
            className="work-area__button workflow-run-banner__danger"
            disabled={busy || !actionReady(pending, valueOf(pending))}
            onClick={() => {
              onChoose(pending);
              setChosenDanger(null);
            }}
          >
            {pending.label}
          </button>
          <button type="button" className="work-area__button" onClick={() => setChosenDanger(null)}>
            Cancel
          </button>
        </span>
      ) : null}
    </div>
  );
}
