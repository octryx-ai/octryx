import { useEffect, useState } from "react";

import { readJson } from "../chatApiClient";
import { loopLimitBody, workItemLimitsPath } from "../workflowRun/workflowRunRequests";
import { loadWorkItems } from "./workApi";
import { ADVANCED_FIELDS } from "./workItemRunStartModel";
import {
  budgetWithCost,
  cascadeNote,
  cascades,
  childItems,
  childLimitsBody,
  costBudgetValue,
  limitsBody,
  limitsDraft,
  limitsSaveError,
  readItemLimits,
  type ItemLimits,
} from "./workItemLimitsModel";
import type { WorkItem } from "./workItemTypes";

const putLimits = (id: string, body: unknown) =>
  readJson<unknown>(workItemLimitsPath(id), { method: "PUT", body: JSON.stringify(body) });

// Work item › Start workflow › Advanced: "Rounds per loop" and "Cost budget (USD)", saved together (the PUT replaces
// the item's limits). On an Epic or a Story the cost budget can also go to every child item, one PUT per child.
export function WorkItemLimitsFields({ item, onHasValue }: { item: WorkItem; onHasValue: (set: boolean) => void }) {
  const [saved, setSaved] = useState<ItemLimits>({ loopLimit: null, budget: {} });
  const [loop, setLoop] = useState("");
  const [cost, setCost] = useState("");
  const [cascade, setCascade] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<{ loop?: string; cost?: string; save?: string }>({});
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void readJson<unknown>(workItemLimitsPath(item.id)).then((raw) => {
      if (cancelled) return;
      const limits = readItemLimits(raw);
      const draft = limitsDraft(limits);
      setSaved(limits);
      setLoop(draft.loop);
      setCost(draft.cost);
      onHasValue(Boolean(draft.loop || draft.cost));
    }).catch(() => undefined);
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per item
  }, [item.id]);

  async function save() {
    const loopBody = loopLimitBody(loop);
    const costValue = costBudgetValue(cost);
    const problems = { loop: "error" in loopBody ? loopBody.error : undefined, cost: "error" in costValue ? costValue.error : undefined };
    setErrors(problems);
    setNote(null);
    if ("error" in loopBody || "error" in costValue) return;
    setBusy(true);
    try {
      const budget = budgetWithCost(saved.budget, costValue.value);
      setSaved(readItemLimits(await putLimits(item.id, limitsBody(loopBody.loop_limit ?? null, budget))));
      if (cascade && cascades(item)) {
        setNote(await saveOnChildren(item, costValue.value));
      } else {
        setNote("Saved. Runs started from now on use it, capped by the platform ceiling.");
      }
    } catch (error) {
      setErrors({ save: limitsSaveError(error) });
    } finally {
      setBusy(false);
    }
  }

  const id = (name: string) => `run-${name}-${item.id}`;
  return (
    <div className="work-run-start__limits" data-testid="work-run-limits">
      <div className="admin-panel__field">
        <label htmlFor={id("limit")}>{ADVANCED_FIELDS.loopLimit.label}</label>
        <input id={id("limit")} className="admin-panel__input" type="number" min={1} value={loop}
          placeholder={ADVANCED_FIELDS.loopLimit.placeholder} aria-invalid={errors.loop ? true : undefined}
          onChange={(event) => { setLoop(event.target.value); setErrors({}); }} />
        <p className={`work-run-start__hint${errors.loop ? " work-run-start__hint--error" : ""}`} role={errors.loop ? "alert" : undefined}>
          {errors.loop ?? ADVANCED_FIELDS.loopLimit.hint}
        </p>
      </div>
      <div className="admin-panel__field">
        <label htmlFor={id("cost")}>{ADVANCED_FIELDS.costBudget.label}</label>
        <input id={id("cost")} className="admin-panel__input" type="text" inputMode="decimal" value={cost}
          placeholder={ADVANCED_FIELDS.costBudget.placeholder} aria-invalid={errors.cost ? true : undefined}
          data-testid="work-run-cost-budget" onChange={(event) => { setCost(event.target.value); setErrors({}); }} />
        <p className={`work-run-start__hint${errors.cost ? " work-run-start__hint--error" : ""}`} role={errors.cost ? "alert" : undefined}>
          {errors.cost ?? ADVANCED_FIELDS.costBudget.hint}
        </p>
      </div>
      {cascades(item) ? (
        <label className="admin-panel__checkbox" data-testid="work-run-cost-cascade">
          <input type="checkbox" checked={cascade} onChange={(event) => setCascade(event.target.checked)} />
          Also set for all child items
        </label>
      ) : null}
      <div className="work-run-start__actions">
        <button type="button" className="work-area__button" disabled={busy} data-testid="work-run-limits-save"
          onClick={() => void save()}>{busy ? "Saving…" : "Save run limits"}</button>
      </div>
      {errors.save ? <p className="work-run-start__hint work-run-start__hint--error" role="alert">{errors.save}</p> : null}
      {note ? <p className="work-detail__empty" role="status">{note}</p> : null}
    </div>
  );
}

/** The same cost budget on every child (each keeps its own loop limit and other budget keys). */
async function saveOnChildren(item: WorkItem, cost: number | null): Promise<string> {
  const children = childItems(item, await loadWorkItems(1000, item.project_id ?? ""));
  const failed: string[] = [];
  for (const child of children) {
    try {
      const limits = readItemLimits(await readJson<unknown>(workItemLimitsPath(child.id)));
      await putLimits(child.id, childLimitsBody(limits, cost));
    } catch {
      failed.push(child.source_key || child.title);
    }
  }
  if (!children.length) return "Saved. This item has no child items yet.";
  return cascadeNote(children.length - failed.length, failed);
}
