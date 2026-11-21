import { useMemo, useState } from "react";

import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { Checks, LEVEL_COLORS, ToggleRow, levelColorClass } from "../settingsKit/SettingsKit";
import type { CatalogLevel } from "./classificationLevelCatalog";
import type { LevelRules, MatrixRow } from "./classificationMatrixRows";
import { cellDisplay, cellValue } from "./classificationMatrixRows";
import { levelKeyFrom, newLevelChecks, positionOptions, rankAfter, restrictingRows } from "./classificationLevelCatalog";

export type LevelDraft = { level: CatalogLevel; copyFrom: string | null };

function Swatches({ value, onChange, disabled }: { value: string; onChange: (color: string) => void; disabled?: boolean }) {
  return (
    <div className="sk-swatches" role="radiogroup" aria-label="Colour">
      {LEVEL_COLORS.map((color) => (
        <button key={color} type="button" role="radio" aria-checked={value === color} aria-label={color} disabled={disabled}
          className={`sk-swatch ${levelColorClass(color)}`} onClick={() => onChange(color)} />
      ))}
    </div>
  );
}

// Add level: name, the immutable key it gives, the position between two
// levels (a free stored rank; existing ranks never move), colour, description, whether models may process it, and the
// level its rules start from (default: the next stricter level, so a new level never starts more permissive).
export function ClassificationAddLevelDrawer({ catalog, levels, rows, onClose, onSave }: {
  catalog: CatalogLevel[];
  levels: LevelRules[];
  rows: MatrixRow[];
  onClose: () => void;
  onSave: (draft: LevelDraft) => void;
}) {
  const [name, setName] = useState("");
  const [position, setPosition] = useState(Math.max(0, catalog.length - 2));
  const [color, setColor] = useState("custom");
  const [description, setDescription] = useState("");
  const [modelsAllowed, setModelsAllowed] = useState(true);
  const stricter = (index: number) => (catalog[index + 1] ?? catalog[index])?.key ?? "";
  const [copyFrom, setCopyFrom] = useState(() => stricter(Math.max(0, catalog.length - 2)));

  const key = levelKeyFrom(name);
  const checks = newLevelChecks(catalog, key, name, position);
  const rank = rankAfter(catalog, position);
  const sourceRules = levels.find((item) => item.level === copyFrom)?.rules;
  const generated = useMemo(() => restrictingRows(rows, sourceRules), [rows, sourceRules]);
  const sourceLabel = catalog.find((level) => level.key === copyFrom)?.label ?? copyFrom;

  return (
    <SettingsDrawer eyebrow="Classification · Draft" title="Add level" size="detail" onClose={onClose}
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="level-save"
            disabled={checks.some((check) => check.state === "bad") || rank === null}
            onClick={() => onSave({
              level: { key, rank: rank ?? 0, label: name.trim(), color, description: description.trim(), models_allowed: modelsAllowed, builtin: false },
              copyFrom,
            })}>
            Add to draft
          </button>
        </>
      )}>
      <div className="sk-page" data-testid="classification-add-level">
        <div className="admin-panel__form-grid">
          <label className="admin-panel__field"><span>Name</span>
            <input value={name} data-testid="level-name" onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="admin-panel__field"><span>Key (cannot change later)</span>
            <input value={key} readOnly data-testid="level-key" />
          </label>
        </div>
        <label className="admin-panel__field"><span>Position</span>
          <select value={String(position)} data-testid="level-position"
            onChange={(event) => { const next = Number(event.target.value); setPosition(next); setCopyFrom(stricter(next)); }}>
            {positionOptions(catalog).map((option) => <option key={option.index} value={String(option.index)}>{option.text}</option>)}
          </select>
        </label>
        <div className="admin-panel__field"><span>Colour</span><Swatches value={color} onChange={setColor} /></div>
        <label className="admin-panel__field"><span>Description (shown to everyone who picks a level)</span>
          <textarea rows={2} value={description} data-testid="level-description" onChange={(event) => setDescription(event.target.value)} />
        </label>
        <ToggleRow title="Models may process this level" on={modelsAllowed} onChange={setModelsAllowed} testId="level-models"
          sub="Off = no model, local or remote, may see content at this level." />
        <label className="admin-panel__field"><span>Start rules from</span>
          <select value={copyFrom} data-testid="level-copy" onChange={(event) => setCopyFrom(event.target.value)}>
            {catalog.map((level) => (
              <option key={level.key} value={level.key}>
                {level.label}{level.key === stricter(position) ? " (next stricter — recommended)" : ""}
              </option>
            ))}
          </select>
        </label>
        <div className="work-detail__section"><h3>Checks</h3><Checks items={checks} testId="level-checks" /></div>
        <div className="work-detail__section">
          <h3>Generated policies</h3>
          <pre className="sk-code" data-testid="level-generated">
            {generated.length
              ? generated.map((row) => `// ${row.label}: ${cellDisplay(row, cellValue(row, sourceRules)).text}\n@id("classification:${key || "…"}:${row.policySuffix}")\nforbid (principal, action, resource)\n  when { context.workspace.classification == "${key || "…"}" … };`).join("\n\n")
              : `// No restricting rules (copied from ${sourceLabel})`}
            {!modelsAllowed ? `\n\n@id("classification:${key || "…"}:no-models")\nforbid (principal, action == Action::"call_model", resource)\n  when { context.workspace.classification == "${key || "…"}" };` : ""}
          </pre>
        </div>
      </div>
    </SettingsDrawer>
  );
}

// A level's own settings: name, colour, description, the model switch (built-ins keep theirs) and, for a custom
// level, retire (refused by the server while anything still uses the level).
export function ClassificationEditLevelDrawer({ level, editable, onClose, onSave, onRetire }: {
  level: CatalogLevel;
  editable: boolean;
  onClose: () => void;
  onSave: (level: CatalogLevel) => void;
  onRetire: () => void;
}) {
  const [label, setLabel] = useState(level.label);
  const [color, setColor] = useState(level.color);
  const [description, setDescription] = useState(level.description);
  const [modelsAllowed, setModelsAllowed] = useState(level.models_allowed);
  const changed = label.trim() !== level.label || color !== level.color || description.trim() !== level.description
    || modelsAllowed !== level.models_allowed;
  return (
    <SettingsDrawer eyebrow={`Classification · Level · rank ${level.rank}`} title={level.label} size="edit" onClose={onClose}
      footer={editable ? (
        <>
          {!level.builtin ? (
            <button type="button" className="admin-panel__action-btn admin-panel__danger-btn" data-testid="level-retire" onClick={onRetire}>Retire</button>
          ) : null}
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="level-edit-save"
            disabled={!changed || !label.trim()}
            onClick={() => onSave({ ...level, label: label.trim(), color, description: description.trim(), models_allowed: modelsAllowed })}>
            Add to draft
          </button>
        </>
      ) : <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>}>
      <div className="sk-page" data-testid="classification-edit-level">
        <label className="admin-panel__field"><span>Name</span>
          <input value={label} disabled={!editable} data-testid="level-edit-name" onChange={(event) => setLabel(event.target.value)} />
        </label>
        <div className="admin-panel__field"><span>Key</span><span className="admin-policy-inline-code">{level.key}</span></div>
        <div className="admin-panel__field"><span>Colour</span><Swatches value={color} onChange={setColor} disabled={!editable} /></div>
        <label className="admin-panel__field"><span>Description</span>
          <textarea rows={2} value={description} disabled={!editable} onChange={(event) => setDescription(event.target.value)} />
        </label>
        <ToggleRow title="Models may process this level" on={modelsAllowed} disabled={!editable || level.builtin} onChange={setModelsAllowed}
          sub={level.builtin ? "Fixed for a built-in level." : "Off = no model, local or remote, may see content at this level."} />
        {level.builtin ? <p className="sk-hint">Built-in levels can be renamed and described, never retired.</p> : null}
      </div>
    </SettingsDrawer>
  );
}
