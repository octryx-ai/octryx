import { useEffect, useId } from "react";

import { readJson } from "../chatApiClient";
import { useEffectiveEngine } from "../engines/useEffectiveEngine";
import { ADVANCED_FIELDS } from "../work/workItemRunStartModel";
import { RunModelSelect } from "../workflowRun/RunModelSelect";
import { workItemLimitsPath } from "../workflowRun/workflowRunRequests";
import { runOnTarget, storedCost } from "./startCardChoices";

// The start card's "Model" (below "Run on") and "Advanced › Cost budget (USD)". The model list is the work item
// dialog's (RunModelSelect) for the device the "Run on" key names. The cost field is prefilled with the item's stored
// budget; the answer carries it, so it is set for a new item too.
export function StartModelBudget({
  projectId,
  runOn,
  model,
  onModel,
  modelError,
  itemId,
  cost,
  onCost,
  costError,
  disabled,
}: {
  projectId: string;
  runOn: string;
  model: string;
  onModel: (model: string) => void;
  modelError: string | null;
  itemId: string | null;
  cost: string;
  onCost: (cost: string) => void;
  costError: string | null;
  disabled: boolean;
}) {
  const engine = useEffectiveEngine(projectId);
  const modelId = useId();
  const costId = useId();

  useEffect(() => {
    if (!itemId) return;
    let cancelled = false;
    void readJson<unknown>(workItemLimitsPath(itemId)).then((raw) => {
      if (cancelled) return;
      const stored = storedCost(raw);
      onCost(stored === null ? "" : String(stored));
    }).catch(() => undefined);
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per item
  }, [itemId]);

  const field = ADVANCED_FIELDS.costBudget;
  return (
    <>
      <RunModelSelect id={modelId} projectId={projectId} engine={engine} target={runOnTarget(runOn)} value={model}
        error={modelError} onChange={onModel} />
      <details className="work-run-start__advanced workflow-start__advanced" data-testid="workflow-start-advanced"
        open={Boolean(cost || costError) || undefined}>
        <summary>Advanced</summary>
        <div className="admin-panel__field">
          <label htmlFor={costId}>{field.label}</label>
          <input id={costId} className="admin-panel__input" type="text" inputMode="decimal" value={cost}
            placeholder={field.placeholder} disabled={disabled}
            aria-invalid={costError ? true : undefined} data-testid="workflow-start-cost-budget"
            onChange={(event) => onCost(event.target.value)} />
          <p className={`work-run-start__hint${costError ? " work-run-start__hint--error" : ""}`}
            role={costError ? "alert" : undefined}>
            {costError ?? "The Work item's runs, this one first, pause when their model cost reaches this amount; its child items inherit it."}
          </p>
        </div>
      </details>
    </>
  );
}
