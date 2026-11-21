import { useState } from "react";

// The builder's pickers: chips for real entities ("✓ selected" / "+ available", the
// admin-policy-chip of the design system) and a free-text list for commands, prefixes and paths.

export function ChipSet({ options, selected, onToggle, label = (value) => value, testId, required = false, disabled = false, addPlaceholder }: {
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
  label?: (value: string) => string;
  testId: string;
  required?: boolean;
  disabled?: boolean;
  /** Offer a free-text entry for values the picker does not list (e.g. a model alias not admitted yet). */
  addPlaceholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const values = [...selected.filter((value) => !options.includes(value)), ...options];
  const add = () => {
    const value = draft.trim();
    if (value && !selected.includes(value)) onToggle(value);
    setDraft("");
  };
  const adder = addPlaceholder ? (
    <div className="policies__row">
      <input className="policies__input-inline" value={draft} placeholder={addPlaceholder} data-testid={`${testId}-input`}
        onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} />
      <button type="button" className="admin-panel__action-btn" data-testid={`${testId}-add`} onClick={add}>Add</button>
    </div>
  ) : null;
  if (!values.length) return adder ?? <div className="policies__sub">Nothing to pick here yet.</div>;
  return (
    <div className="policies__pane">
      <div className="policies__chips" data-testid={testId}>
        {values.map((value) => {
          const on = selected.includes(value);
          return (
            <button key={value} type="button" disabled={disabled} aria-pressed={on} data-testid={`${testId}-chip`} data-value={value}
              className={`admin-policy-chip${on ? "" : " admin-policy-chip--secondary policies__chip-off"}${required && !selected.length ? " policies__chip--required" : ""}`}
              onClick={() => onToggle(value)}>
              {on ? "✓ " : "+ "}{label(value)}
            </button>
          );
        })}
      </div>
      {adder}
    </div>
  );
}

export function FreeList({ values, onChange, placeholder, testId, required = false }: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  testId: string;
  required?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const value = draft.trim();
    if (value && !values.includes(value)) onChange([...values, value]);
    setDraft("");
  };
  return (
    <div className="policies__pane" data-testid={testId}>
      {values.length ? (
        <div className="policies__chips">
          {values.map((value) => (
            <button key={value} type="button" className="admin-policy-chip" data-testid={`${testId}-remove`}
              aria-label={`Remove ${value}`} onClick={() => onChange(values.filter((item) => item !== value))}>{value} ✕</button>
          ))}
        </div>
      ) : null}
      <div className="policies__row">
        <input className={`policies__input-inline${required && !values.length ? " policies__chip--required" : ""}`} value={draft} placeholder={placeholder}
          data-testid={`${testId}-input`} onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} />
        <button type="button" className="admin-panel__action-btn" data-testid={`${testId}-add`} onClick={add}>Add</button>
      </div>
    </div>
  );
}

export function GroupLabel({ children }: { children: string }) {
  return <div className="policies__group-label">{children}</div>;
}
