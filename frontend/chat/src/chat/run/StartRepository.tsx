import { useId, useState } from "react";

import type { WorkflowStartRepository } from "./workflowStartModel";

// The repository a phased start's run works in (`start.repository`). A known one is a line with where it comes from
// and a small "Change"; a missing one is a required choice from the Workspace's repositories. A refusal of the start
// (409 with the server's sentence, 422) stands here, at the choice it is about.
export function StartRepository({
  repository,
  value,
  onChange,
  editable,
  disabled,
  problem,
}: {
  repository: WorkflowStartRepository;
  value: string;
  onChange: (id: string) => void;
  editable: boolean;
  disabled: boolean;
  problem: string | null;
}) {
  const [changing, setChanging] = useState(false);
  const id = useId();
  const chosen = repository.options.find((option) => option.id === value);
  const known = repository.name;
  const choosing = editable && (!known || changing) && repository.options.length > 0;

  return (
    <div className="workflow-start__repository" data-testid="workflow-start-repository">
      {choosing ? (
        <div className="admin-panel__field">
          <label htmlFor={id}>Repository</label>
          <select
            id={id}
            className="admin-panel__input"
            value={value || (changing ? repository.id ?? "" : "")}
            disabled={disabled}
            aria-invalid={Boolean(problem) || undefined}
            onChange={(event) => onChange(event.target.value)}
          >
            {!known || !repository.id ? <option value="">{known ?? "Choose a repository"}</option> : null}
            {repository.options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <p className="workflow-start__repository-line">
          <span className="workflow-start__repository-label">Repository:</span>{" "}
          {chosen?.name ?? known ?? "none yet"}
          {!chosen && repository.sourceText ? <span className="workflow-start__meta"> · {repository.sourceText}</span> : null}
          {chosen ? <span className="workflow-start__meta"> · chosen by you</span> : null}
          {editable && known && repository.options.length > (repository.id ? 1 : 0) ? (
            <button type="button" className="ds-btn ds-btn--sm ds-btn--ghost workflow-start__change" disabled={disabled}
              onClick={() => setChanging(true)}>
              Change
            </button>
          ) : null}
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
