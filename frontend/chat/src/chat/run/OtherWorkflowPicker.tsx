import { useId, useState } from "react";

import type { WorkflowOption } from "../../chatOptionTypes";
import { otherWorkflowChoices } from "./workflowProposalAnswer";

// "Other workflow…" on a pending workflow proposal: a searchable list from the composer's catalog, without the
// workflow the card proposes now. Choosing one answers the proposal with `other` + `workflow_key`; the card then
// re-renders from the returned chat state. A refusal (422, 409) stays here in words.
export function OtherWorkflowPicker({
  options,
  currentKey,
  disabled,
  onPick,
  onClose,
}: {
  options: readonly WorkflowOption[];
  currentKey: string | null;
  disabled: boolean;
  onPick: (workflowKey: string, title: string) => Promise<void>;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const searchId = useId();
  const all = otherWorkflowChoices(options, currentKey);
  const choices = otherWorkflowChoices(options, currentKey, query);

  async function pick(key: string, title: string) {
    if (disabled || busyKey) return;
    setBusyKey(key);
    setProblem(null);
    try {
      await onPick(key, title);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The workflow could not be changed.");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div className="workflow-other" data-testid="workflow-other-picker">
      <div className="workflow-other__head">
        <label className="workflow-other__label" htmlFor={searchId}>
          Choose another workflow
        </label>
        <button type="button" className="ds-btn ds-btn--sm ds-btn--ghost" onClick={onClose}>
          Close
        </button>
      </div>
      {all.length > 6 ? (
        <input
          id={searchId}
          className="admin-panel__input workflow-other__search"
          type="search"
          placeholder="Search workflows"
          value={query}
          autoFocus
          onChange={(event) => setQuery(event.target.value)}
        />
      ) : null}
      {choices.length ? (
        <ul className="workflow-other__list" aria-label="Workflows">
          {choices.map((choice) => (
            <li key={choice.key}>
              <button
                type="button"
                className="workflow-other__option"
                data-workflow-key={choice.key}
                disabled={disabled || busyKey !== null}
                onClick={() => void pick(choice.key, choice.title)}
              >
                <span className="workflow-other__title">
                  {busyKey === choice.key ? "Switching…" : choice.title}
                </span>
                {choice.description ? (
                  <span className="workflow-other__description">{choice.description}</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="workflow-other__empty">
          {all.length ? "No workflow matches this search." : "No other workflow is published for this Workspace."}
        </p>
      )}
      {problem ? (
        <p className="workflow-start__problem" role="alert">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
