import { useState } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import type { MatrixRow } from "./classificationMatrixRows";
import { cellDisplay, cellValue } from "./classificationMatrixRows";
import { overrideOptions, overrideRows, overrideValue, setOverride } from "./classificationOverridesModel";
import type { Rules } from "./classificationPolicyModel";

// A Workspace's classification: its level and the stricter-only overrides. Looser
// values are shown but cannot be picked; to loosen, change the rule for the whole level.
export function ClassificationOverrideDrawer({ name, levelLabel, levelRules, rows, overrides, busy, problem, onClose, onSave }: {
  name: string;
  levelLabel: string;
  levelRules: Rules | undefined;
  rows: MatrixRow[];
  overrides: Rules;
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (overrides: Rules) => void;
}) {
  const [draft, setDraft] = useState<Rules>(overrides);
  const changed = JSON.stringify(draft) !== JSON.stringify(overrides);
  return (
    <SettingsDrawer eyebrow="Classification · Workspace" title={name} size="detail" onClose={onClose}
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="override-save"
            disabled={busy || !changed} onClick={() => onSave(draft)}>
            Save
          </button>
        </>
      )}>
      <div className="sk-page" data-testid="classification-override-drawer">
        <div className="admin-panel__field"><span>Level</span><b>{levelLabel}</b></div>
        <p className="sk-hint">The level is set in the Workspace's own settings (Rules → Classification).</p>
        <div className="work-detail__section">
          <h3>Stricter overrides</h3>
          {overrideRows(rows).map((row) => {
            const levelValue = cellValue(row, levelRules);
            const current = overrideValue(row, draft) ?? levelValue;
            const options = overrideOptions(row, levelValue);
            const chosen = Math.max(0, options.findIndex((option) => option.value === current));
            return (
              <div key={row.key} className="sk-trow">
                <div className="sk-trow__txt">
                  <div className="sk-name">{row.label}</div>
                  <div className="sk-sub">Level: {cellDisplay(row, levelValue).text}</div>
                </div>
                <select className="admin-users__toolbar-select" value={String(chosen)} data-testid={`override-${row.key}`}
                  aria-label={row.label}
                  onChange={(event) => setDraft(setOverride(draft, row, options[Number(event.target.value)].value, levelValue))}>
                  {options.map((option, index) => (
                    <option key={option.text} value={String(index)} disabled={!option.allowed}>
                      {option.text}{option.level ? " (level)" : option.allowed ? "" : " — looser, not allowed"}
                    </option>
                  ))}
                </select>
              </div>
            );
          })}
        </div>
        <p className="sk-note">Looser values are not offered: an override can only restrict. To loosen, change the rule for the whole level.</p>
        {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
      </div>
    </SettingsDrawer>
  );
}
