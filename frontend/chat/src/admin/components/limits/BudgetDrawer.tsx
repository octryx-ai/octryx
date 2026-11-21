import { useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { SidePanel } from "../../../layout/SidePanel";
import { PERIODS, budgetPayload, draftFromBudget, emptyBudget } from "./limitsContract";
import type { Budget, BudgetDraft, Overview } from "./limitsContract";

const SAVE = "/admin/chat/api/panel/budget-policies";

type Props = { budget: Budget | null; overview: Overview; onClose: () => void; onSaved: () => void };

// Add or change a budget period (BudgetPolicy, enforced on every model call of its scope). Scope: a Workspace or a
// person; a budget is turned off, never deleted, so its history stays readable.
export function BudgetDrawer({ budget, overview, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<BudgetDraft>(() => (budget ? draftFromBudget(budget) : emptyBudget()));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const update = (patch: Partial<BudgetDraft>) => { setDraft((current) => ({ ...current, ...patch })); setError(""); };
  const targets = draft.scope === "person" ? overview.users : overview.workspaces;

  const save = async () => {
    const built = budgetPayload(draft, overview);
    if ("error" in built) {
      setError(built.error);
      return;
    }
    setSaving(true);
    try {
      await readJson<unknown>(SAVE, { method: "POST", body: JSON.stringify(built.payload) });
      onSaved();
    } catch (failure) {
      setError(`Not saved: ${failure instanceof Error ? failure.message : "the budget was refused"}.`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <SidePanel
      title={budget ? "Change budget" : "Add budget"}
      onClose={onClose}
      testId="budget-panel"
      footer={
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={saving}
            data-testid="budget-save" onClick={() => void save()}>
            {saving ? "Saving…" : "Save budget"}
          </button>
        </>
      }
    >
      <div className="limits__form">
        <label className="admin-panel__field">
          <span>Scope</span>
          <select value={draft.scope} onChange={(event) => update({ scope: event.target.value as BudgetDraft["scope"], targetId: "" })}>
            <option value="workspace">A Workspace</option>
            <option value="person">A person</option>
          </select>
        </label>
        <label className="admin-panel__field">
          <span>{draft.scope === "person" ? "Person" : "Workspace"}</span>
          <select value={draft.targetId} onChange={(event) => update({ targetId: event.target.value })} data-testid="budget-target">
            <option value="">Choose</option>
            {targets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="admin-panel__field">
          <span>Period</span>
          <select value={draft.period} onChange={(event) => update({ period: event.target.value })}>
            {PERIODS.map((period) => <option key={period.value} value={period.value}>{period.label}</option>)}
          </select>
        </label>
        <label className="admin-panel__field">
          <span>Amount (USD)</span>
          <input inputMode="decimal" value={draft.amount} onChange={(event) => update({ amount: event.target.value })}
            data-testid="budget-amount" />
        </label>
        <label className="admin-panel__field">
          <span>Warn at (% of the amount)</span>
          <input inputMode="numeric" value={draft.warnAt} onChange={(event) => update({ warnAt: event.target.value })} />
        </label>
        <label className="admin-panel__field">
          <span>Stop at (% of the amount)</span>
          <input inputMode="numeric" value={draft.stopAt} onChange={(event) => update({ stopAt: event.target.value })} />
        </label>
        {budget ? (
          <label className="admin-panel__checkbox">
            <input type="checkbox" checked={draft.active} onChange={(event) => update({ active: event.target.checked })} />
            Budget is on
          </label>
        ) : null}
        {error ? <p className="admin-panel__error" role="alert">{error}</p> : null}
      </div>
    </SidePanel>
  );
}
