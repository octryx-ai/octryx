// Building blocks of the designer's side panel: labelled fields in the admin panel style (admin-panel__field),
// each showing its own plain-language problems underneath. Pure: they render what they get and report changes.
import { useEffect, useId, useState, type ReactNode } from "react";

import { ActionMenu } from "../../../../workflowSurfaces/ActionMenu";

import type { FieldIssue } from "../types";

export function Problems({ issues }: { issues: FieldIssue[] }) {
  if (!issues.length) return null;
  return (
    <>
      {issues.map((issue) => (
        <span key={`${issue.path}:${issue.message}`} className="dsi-problem" role="alert">
          {issue.message}
        </span>
      ))}
    </>
  );
}

type Base = { label: string; hint?: string; issues?: FieldIssue[]; disabled?: boolean };

export function TextField({ label, hint, issues = [], disabled, value, multiline, placeholder, onChange }: Base & {
  value: string; multiline?: boolean; placeholder?: string; onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <label className="admin-panel__field" htmlFor={id}>
      <span>{label}</span>
      {multiline ? (
        <textarea id={id} className="admin-panel__input" rows={3} value={value} disabled={disabled}
          placeholder={disabled ? undefined : placeholder} onChange={(event) => onChange(event.target.value)} aria-invalid={issues.length > 0} />
      ) : (
        <input id={id} className="admin-panel__input" value={value} disabled={disabled} placeholder={disabled ? undefined : placeholder}
          onChange={(event) => onChange(event.target.value)} aria-invalid={issues.length > 0} />
      )}
      {hint ? <span className="admin-panel__hint">{hint}</span> : null}
      <Problems issues={issues} />
    </label>
  );
}

export function SelectField({ label, hint, issues = [], disabled, value, options, empty, onChange }: Base & {
  value: string; options: { value: string; label: string }[]; empty?: string; onChange: (value: string) => void;
}) {
  const id = useId();
  const known = options.some((option) => option.value === value);
  return (
    <label className="admin-panel__field" htmlFor={id}>
      <span>{label}</span>
      <select id={id} className="admin-panel__input" value={value} disabled={disabled}
        onChange={(event) => onChange(event.target.value)} aria-invalid={issues.length > 0}>
        {empty !== undefined || !value ? <option value="">{empty ?? "Choose…"}</option> : null}
        {value && !known ? <option value={value}>No longer available</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {hint ? <span className="admin-panel__hint">{hint}</span> : null}
      <Problems issues={issues} />
    </label>
  );
}

export function CheckList({ label, hint, issues = [], disabled, values, options: known, gone, onChange }: Base & {
  values: string[]; options: { value: string; label: string }[]; onChange: (values: string[]) => void;
  /** How a chosen value that is no longer offered reads, so it can still be unticked. */
  gone?: (value: string) => string;
}) {
  const options = [...known, ...values.filter((value) => !known.some((option) => option.value === value))
    .map((value) => ({ value, label: gone ? gone(value) : "No longer available" }))];
  return (
    <fieldset className="admin-panel__field dsi-checklist" aria-invalid={issues.length > 0}>
      <legend>{label}</legend>
      {options.map((option) => (
        <label key={option.value} className="admin-panel__checkbox dsi-checklist__item">
          <input type="checkbox" checked={values.includes(option.value)} disabled={disabled}
            onChange={(event) => onChange(event.target.checked
              ? [...values, option.value]
              : values.filter((value) => value !== option.value))} />
          <span>{option.label}</span>
        </label>
      ))}
      {!options.length ? <span className="admin-panel__hint">Nothing to choose yet.</span> : null}
      {hint ? <span className="admin-panel__hint">{hint}</span> : null}
      <Problems issues={issues} />
    </fieldset>
  );
}

export function ToggleField({ label, hint, disabled, checked, onChange }: Base & {
  checked: boolean; onChange: (checked: boolean) => void;
}) {
  return (
    <div className="dsi-toggle">
      <label className="admin-panel__checkbox">
        <input type="checkbox" checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
        <span>{label}</span>
      </label>
      {hint ? <span className="admin-panel__hint">{hint}</span> : null}
    </div>
  );
}

/** A chosen subset of a long list (tools): the chosen ones as removable chips, the rest behind one "Add" select. */
export function PickList({ label, hint, issues = [], disabled, values, options, addLabel, emptyText, onChange }: Base & {
  values: string[]; options: { value: string; label: string }[]; addLabel: string; emptyText: string;
  onChange: (values: string[]) => void;
}) {
  const id = useId();
  const name = (value: string) => options.find((option) => option.value === value)?.label ?? value;
  const rest = options.filter((option) => !values.includes(option.value));
  return (
    <div className="admin-panel__field dsi-picklist" role="group" aria-labelledby={id} aria-invalid={issues.length > 0}>
      <span id={id}>{label}</span>
      {values.length ? (
        <ul className="dsi-chips">
          {values.map((value) => (
            <li key={value} className={`dsi-chip${issues.some((issue) => issue.message.includes(name(value))) ? " dsi-chip--problem" : ""}`}>
              {name(value)}
              {!disabled ? (
                <button type="button" className="dsi-chip__remove" aria-label={`Remove ${name(value)}`}
                  onClick={() => onChange(values.filter((item) => item !== value))}>×</button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : emptyText ? <span className="admin-panel__hint">{emptyText}</span> : null}
      {!disabled && rest.length ? (
        <select className="admin-panel__input dsi-picklist__add" value="" aria-label={addLabel}
          onChange={(event) => event.target.value && onChange([...values, event.target.value])}>
          <option value="">{addLabel}</option>
          {rest.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      ) : null}
      {hint ? <span className="admin-panel__hint">{hint}</span> : null}
      <Problems issues={issues} />
    </div>
  );
}

/** Path patterns, one per line (``src/**``); an empty box means "no rule". */
export function LinesField({ label, hint, issues = [], disabled, values, placeholder, onChange }: Base & {
  values: string[] | undefined; placeholder?: string; onChange: (values: string[] | undefined) => void;
}) {
  const [draft, setDraft] = useState((values ?? []).join("\n"));
  useEffect(() => setDraft((values ?? []).join("\n")), [values]);
  return (
    <TextField label={label} hint={hint} issues={issues} disabled={disabled} multiline value={draft}
      placeholder={placeholder} onChange={(text) => {
        setDraft(text);
        const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
        onChange(lines.length ? lines : undefined);
      }} />
  );
}

export function NumberField({ label, hint, issues = [], disabled, value, min, onChange }: Base & {
  value: number | null; min?: number; onChange: (value: number | null) => void;
}) {
  const id = useId();
  return (
    <label className="admin-panel__field" htmlFor={id}>
      <span>{label}</span>
      <input id={id} type="number" className="admin-panel__input" min={min} value={value ?? ""} disabled={disabled}
        onChange={(event) => onChange(event.target.value === "" ? null : Math.trunc(Number(event.target.value)))}
        aria-invalid={issues.length > 0} />
      {hint ? <span className="admin-panel__hint">{hint}</span> : null}
      <Problems issues={issues} />
    </label>
  );
}

/** Raw values only behind "Technical details": a JSON object, checked on leaving the field. */
export function JsonObjectField({ label, value, disabled, issues = [], onChange }: Base & {
  value: unknown; onChange: (value: Record<string, unknown>) => void;
}) {
  const [draft, setDraft] = useState(JSON.stringify(value ?? {}, null, 2));
  const [problem, setProblem] = useState("");
  useEffect(() => setDraft(JSON.stringify(value ?? {}, null, 2)), [value]);
  const commit = () => {
    try {
      const parsed = JSON.parse(draft || "{}") as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
      setProblem("");
      onChange(parsed as Record<string, unknown>);
    } catch {
      setProblem("Write a set of named values, for example {\"key\": \"value\"}.");
    }
  };
  return (
    <label className="admin-panel__field">
      <span>{label}</span>
      <textarea className="admin-panel__input" rows={4} value={draft} disabled={disabled}
        onChange={(event) => setDraft(event.target.value)} onBlur={commit} />
      {problem ? <span className="dsi-problem" role="alert">{problem}</span> : null}
      <Problems issues={issues} />
    </label>
  );
}

/** Path patterns or names as chips: one short input adds, × removes (no empty multi-line boxes). */
export function ChipInput({ label, hint, issues = [], disabled, values, placeholder, addLabel = "Add", format, onChange }: Base & {
  values: string[]; placeholder?: string; addLabel?: string; format?: (value: string) => string;
  onChange: (values: string[]) => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState("");
  const add = () => {
    const value = draft.trim();
    if (value && !values.includes(value)) onChange([...values, value]);
    setDraft("");
  };
  return (
    <div className="admin-panel__field dsi-chipinput" role="group" aria-labelledby={id} aria-invalid={issues.length > 0}>
      <span id={id}>{label}</span>
      {values.length ? (
        <ul className="dsi-chips">
          {values.map((value) => (
            <li key={value} className="dsi-chip">
              {format ? format(value) : <code className="dsi-chip__code">{value}</code>}
              {!disabled ? (
                <button type="button" className="dsi-chip__remove" aria-label={`Remove ${value}`}
                  onClick={() => onChange(values.filter((item) => item !== value))}>×</button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {!disabled ? (
        <div className="dsi-chipinput__add">
          <input className="admin-panel__input" value={draft} placeholder={placeholder} aria-label={`${label}: ${addLabel}`}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} />
          <button type="button" className="admin-panel__action-btn" disabled={!draft.trim()} onClick={add}>{addLabel}</button>
        </div>
      ) : !values.length ? <span className="admin-panel__hint">None.</span> : null}
      {hint ? <span className="admin-panel__hint">{hint}</span> : null}
      <Problems issues={issues} />
    </div>
  );
}

/** One entry of a list (a check, a step) as a single line; opens to edit. Remove sits in the ⋯ menu. */
export function Card({ title, meta, open, problem, onToggle, onRemove, removeLabel, children }: {
  title: string; meta?: string; open: boolean; problem?: boolean; onToggle: () => void; onRemove?: () => void;
  removeLabel?: string; children: ReactNode;
}) {
  const id = useId();
  return (
    <div className={`dsi-card${open ? " dsi-card--open" : ""}${problem ? " dsi-card--problem" : ""}`}>
      <div className="dsi-card__head">
        <button type="button" className="dsi-card__toggle" aria-expanded={open} aria-controls={id} onClick={onToggle}>
          <span className="dsi-card__chevron" aria-hidden="true">{open ? "▾" : "▸"}</span>
          <span className="dsi-card__title">{problem ? <span className="dsi-card__mark" aria-label="Needs attention">!</span> : null}{title}</span>
          {meta ? <span className="dsi-card__meta">{meta}</span> : null}
        </button>
        {onRemove ? (
          <ActionMenu row={{ objectName: title }} items={[{ label: removeLabel ?? "Remove", danger: true, onSelect: onRemove }]} />
        ) : null}
      </div>
      {open ? <div id={id} className="dsi-card__body">{children}</div> : null}
    </div>
  );
}

export function Technical({ children, open }: { children: React.ReactNode; open?: boolean }) {
  return (
    <details className="ds-advanced" open={open || undefined}>
      <summary className="ds-advanced__summary">Technical details</summary>
      {children}
    </details>
  );
}
