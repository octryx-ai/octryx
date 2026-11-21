// "Other workflow…" on the phone: the Workspace's workflows in a bottom sheet, searchable, without the current one.
import { useEffect, useState } from "react";

import type { WorkflowOption } from "../chatOptionTypes";
import { otherWorkflowChoices } from "../chat/run/workflowProposalAnswer";
import { BottomSheet } from "./BottomSheet";
import { Icon } from "./icons";
import { loadWorkflowCatalog } from "./mobileApi";

// "Other workflow…": the Workspace's workflows in the phone's sheet, searchable, without the current one.
export function OtherWorkflowSheet({
  projectId,
  currentKey,
  onClose,
  onPick,
}: {
  projectId: string;
  currentKey: string;
  onClose: () => void;
  onPick: (workflowKey: string) => Promise<void>;
}) {
  const [options, setOptions] = useState<WorkflowOption[] | null>(null);
  const [query, setQuery] = useState("");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    let alive = true;
    loadWorkflowCatalog(projectId).then(
      (payload) => alive && setOptions(payload.workflows ?? []),
      () => alive && setOptions([]),
    );
    return () => {
      alive = false;
    };
  }, [projectId]);
  const all = otherWorkflowChoices(options, currentKey);
  const choices = otherWorkflowChoices(options, currentKey, query);

  const pick = async (key: string) => {
    if (busyKey) return;
    setBusyKey(key);
    setProblem("");
    try {
      await onPick(key);
    } catch (reason) {
      setProblem(reason instanceof Error ? reason.message : "The workflow could not be changed.");
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <BottomSheet title="Choose another workflow" onClose={onClose}>
      {all.length > 6 && (
        <label className="m-search">
          <Icon name="search" size={18} />
          <input
            type="search"
            aria-label="Search workflows"
            placeholder="Search workflows"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
      )}
      {options === null && <p className="m-empty">Loading…</p>}
      {options !== null && choices.length === 0 && (
        <p className="m-empty">{all.length ? "No workflow matches this search." : "No other workflow is published for this Workspace."}</p>
      )}
      <ul className="m-rows m-group" aria-label="Workflows">
        {choices.map((choice) => (
          <li key={choice.key}>
            <button
              type="button"
              className="m-row m-row-plain"
              data-workflow-key={choice.key}
              disabled={busyKey !== null}
              onClick={() => void pick(choice.key)}
            >
              <span className="m-row-text">
                <b>{busyKey === choice.key ? "Switching…" : choice.title}</b>
                {choice.description && <span>{choice.description}</span>}
              </span>
              <Icon name="chevronRight" size={18} className="m-row-chevron" />
            </button>
          </li>
        ))}
      </ul>
      {problem && <p className="m-error" role="alert">{problem}</p>}
    </BottomSheet>
  );
}
