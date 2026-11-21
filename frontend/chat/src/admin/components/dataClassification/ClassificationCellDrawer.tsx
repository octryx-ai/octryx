import { useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import type { MatrixRow } from "./classificationMatrixRows";
import { cellDisplay, cellOptions, policiesForCell } from "./classificationMatrixRows";
import { loadGeneratedClassificationPolicies } from "./dataClassificationApi";

// One cell of the matrix: its value (editable into the draft unless derived or read-only) and the policy it generates.
export function ClassificationCellDrawer({ row, levelKey, levelLabel, value, editable, hasDraft, onClose, onSave }: {
  row: MatrixRow;
  levelKey: string;
  levelLabel: string;
  value: unknown;
  editable: boolean;
  hasDraft: boolean;
  onClose: () => void;
  onSave: (value: unknown) => void;
}) {
  const { openAdminTab } = useAdminNavigation();
  const options = cellOptions(row, value);
  const [choice, setChoice] = useState(() => Math.max(0, options.findIndex((option) => option.value === value)));
  const [policies, setPolicies] = useState<{ id: string; text: string }[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadGeneratedClassificationPolicies(hasDraft ? "draft" : "published")
      .then((answer) => {
        const list = answer && typeof answer === "object" && Array.isArray((answer as { policies?: unknown }).policies)
          ? (answer as { policies: { id: string; text: string }[] }).policies : [];
        if (!cancelled) setPolicies(policiesForCell(list, levelKey, row));
      })
      .catch(() => { if (!cancelled) setPolicies([]); });
    return () => { cancelled = true; };
  }, [hasDraft, levelKey, row]);

  const canEdit = editable && !row.derived;
  const footer = canEdit ? (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="cell-save"
        disabled={options[choice]?.value === value} onClick={() => onSave(options[choice]?.value)}>
        Add to draft
      </button>
    </>
  ) : <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>;

  return (
    <SettingsDrawer eyebrow="Classification · Draft" title={`${row.label} · ${levelLabel}`} size="edit" onClose={onClose} footer={footer}>
      <div className="sk-page" data-testid="classification-cell-drawer">
        {row.derived ? (
          <p className="sk-hint">
            Derived from each model's clearance: <b>{cellDisplay(row, value).text}</b>. Set it per model in{" "}
            <button type="button" className="sk-link" onClick={() => openAdminTab("modelCatalog")}>Runtime → Model catalog</button>.
          </p>
        ) : (
          <label className="admin-panel__field">
            <span>{row.label}</span>
            <select value={String(choice)} disabled={!canEdit} data-testid="cell-value" onChange={(event) => setChoice(Number(event.target.value))}>
              {options.map((option, index) => <option key={option.text} value={String(index)}>{option.text}</option>)}
            </select>
          </label>
        )}
        {row.notEnforced ? <p className="sk-note">Not enforced yet: the value is stored and shown, no job applies it today.</p> : null}
        {!editable ? <p className="sk-hint">Read-only: platform admins change the classification policy.</p> : null}
        <div className="work-detail__section">
          <h3>Generated policy</h3>
          {policies === null ? <p className="sk-hint" role="status">Loading…</p>
            : policies.length ? <pre className="sk-code" data-testid="cell-policy">{policies.map((policy) => policy.text).join("\n\n")}</pre>
              : <p className="sk-hint">No policy: this value does not restrict anything at {levelLabel}.</p>}
        </div>
      </div>
    </SettingsDrawer>
  );
}
