import { useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";

const PATH = "/api/v1/workflow-runs/limits";
type Ceiling = {
  loop_ceiling: number;
  max_loop_ceiling: number;
  editable: boolean;
};

// On Runtime → Limits & budgets: the highest iteration limit any workflow run
// loop may have. A workflow version sets each loop's n, a Work item may override it; this ceiling caps both, and
// "continue with more iterations" on a paused run stays under it. Only a platform admin changes it.
export function WorkflowRunCeilingField() {
  const [ceiling, setCeiling] = useState<Ceiling | null>(null);
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    readJson<Ceiling>(PATH)
      .then((payload) => {
        if (!active) return;
        setCeiling(payload);
        setDraft(String(payload.loop_ceiling));
      })
      .catch(() => active && setMessage("The setting could not be loaded."));
    return () => {
      active = false;
    };
  }, []);

  const save = async () => {
    try {
      const saved = await readJson<Ceiling>(PATH, {
        method: "PUT",
        body: JSON.stringify({ loop_ceiling: Number(draft) }),
      });
      setCeiling(saved);
      setDraft(String(saved.loop_ceiling));
      setMessage("Saved.");
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "The setting could not be saved.",
      );
    }
  };

  return (
    <fieldset
      className="admin-panel__card"
      disabled={!ceiling?.editable}
      data-testid="workflow-run-ceiling"
    >
      <legend className="admin-panel__section-header">
        Workflow run loops
      </legend>
      <label className="admin-panel__field">
        <span>Platform ceiling (iterations per loop)</span>
        <input
          className="admin-panel__input"
          type="number"
          min={1}
          max={ceiling?.max_loop_ceiling ?? 1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </label>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={() => void save()}
      >
        Save ceiling
      </button>
      {message ? (
        <p className="admin-panel__hint" role="status">
          {message}
        </p>
      ) : null}
    </fieldset>
  );
}
