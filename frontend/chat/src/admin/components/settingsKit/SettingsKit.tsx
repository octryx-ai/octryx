import { useState, type ReactNode } from "react";

import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { StatusLabel } from "../../../layout/StatusLabel";
import "../adminChannels.css";
import "./settingsKit.css";

// Shared pieces of the Settings pages. Controls stay design-system
// controls; this file only adds the switch, the toggle row, live checks and the level dot.

export function ToggleSwitch({ on, label, disabled = false, onChange, testId }: {
  on: boolean;
  label: string;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  testId?: string;
}) {
  const flip = () => { if (!disabled) onChange(!on); };
  return (
    <span className={`toggle-switch sk-toggle ${on ? "toggle-switch--on" : ""}`} role="switch" aria-checked={on}
      aria-label={label} aria-disabled={disabled} tabIndex={disabled ? -1 : 0} data-testid={testId}
      onClick={flip}
      onKeyDown={(event) => {
        if (event.key === " " || event.key === "Enter") {
          event.preventDefault();
          flip();
        }
      }} />
  );
}

export function ToggleRow({ title, sub, on, disabled, onChange, testId }: {
  title: ReactNode;
  sub?: ReactNode;
  on: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  testId?: string;
}) {
  const label = typeof title === "string" ? title : "Toggle";
  return (
    <div className="sk-trow">
      <div className="sk-trow__txt">
        <div className="sk-name">{title}</div>
        {sub ? <div className="sk-sub">{sub}</div> : null}
      </div>
      <ToggleSwitch on={on} label={label} disabled={disabled} onChange={onChange} testId={testId} />
    </div>
  );
}

export type Check = { state: "ok" | "bad" | "info"; text: ReactNode; key?: string };

export function Checks({ items, testId }: { items: Check[]; testId?: string }) {
  return (
    <ul className="sk-checks" data-testid={testId}>
      {items.map((item, index) => (
        <li key={item.key ?? index} className={item.state === "bad" ? "is-bad" : item.state === "info" ? "is-info" : ""}>
          <span>{item.text}</span>
        </li>
      ))}
    </ul>
  );
}

// The colour keys a classification level may carry (stored with the level); unknown keys show the custom colour.
export const LEVEL_COLORS = ["custom", "public", "internal", "confidential", "restricted", "secret"] as const;
export type LevelColor = (typeof LEVEL_COLORS)[number];

export function levelColorClass(color: string | null | undefined): string {
  return `sk-c-${(LEVEL_COLORS as readonly string[]).includes(color ?? "") ? color : "custom"}`;
}

export function LevelTag({ label, color, muted = false }: { label: string; color?: string | null; muted?: boolean }) {
  return (
    <span className="sk-lv">
      <span className={`sk-dot ${levelColorClass(color)}`} aria-hidden="true" />
      {muted ? <span className="sk-muted">{label}</span> : label}
    </span>
  );
}

export function OptionCards<T extends string>({ name, value, options, onChange, disabled = false, label }: {
  name: string;
  value: T | null;
  // badge: a short mark on one option; a string ("Proposal", Spec Studio) is shown as a StatusLabel.
  options: { value: T; title: string; desc: string; disabled?: boolean; badge?: ReactNode }[];
  onChange: (next: T) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <div className="sk-option-grid" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <label key={option.value} className="admin-option-card">
          <input type="radio" name={name} value={option.value} checked={value === option.value}
            disabled={disabled || option.disabled} onChange={() => onChange(option.value)} />
          <span className="admin-option-card__body">
            <span className="admin-option-card__title">
              {option.title}{option.badge ? <> {typeof option.badge === "string"
                ? <StatusLabel label={option.badge} tone="info" /> : option.badge}</> : null}
            </span>
            <span className="admin-option-card__desc">{option.desc}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

// Sub-tab bar of a Settings page: the one tab style (SegmentedTabs, small), the second level under the Admin views.
export function SubTabs<T extends string>({ value, tabs, onChange, label }: {
  value: T;
  tabs: { id: T; label: string }[];
  onChange: (next: T) => void;
  label: string;
}) {
  return (
    <SegmentedTabs size="small" label={label} value={value} onChange={(key) => onChange(key as T)}
      idPrefix={`subtabs-${label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
      tabs={tabs.map((tab) => ({ key: tab.id, label: tab.label, testId: `subtab-${tab.id}` }))} />
  );
}

// A list of short values as chips, each removable, with an inline add (no example placeholder: the label says what).
export function ChipListEditor({ label, values, onChange, tone = "secondary", disabled = false, testId, defaults, problems }: {
  label: string;
  values: string[];
  onChange: (next: string[]) => void;
  tone?: "secondary" | "danger";
  disabled?: boolean;
  testId?: string;
  /** The platform's defaults for this list: their chips say "default", every other chip "added". */
  defaults?: string[];
  /** A problem per value: that chip turns red and the sentence is shown under the chips. */
  problems?: Record<string, string>;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const value = draft.trim();
    if (value && !values.includes(value)) onChange([...values, value]);
    setDraft("");
  };
  return (
    <div className="sk-chip-editor" data-testid={testId}>
      <div className="sk-chips">
        {values.map((value) => (
          <span key={value} className={`admin-policy-chip admin-policy-chip--${problems?.[value] ? "danger" : tone} sk-chip-removable`}
            title={problems?.[value]} aria-invalid={problems?.[value] ? true : undefined}
            data-testid={testId && problems?.[value] ? `${testId}-invalid` : undefined}>
            <span>{value}</span>
            {defaults ? (
              <span className="sk-chip-origin" data-testid={testId ? `${testId}-origin-${value}` : undefined}>
                {defaults.includes(value) ? "default" : "added"}
              </span>
            ) : null}
            {!disabled ? (
              <button type="button" className="sk-chip-remove" aria-label={`Remove ${value}`} onClick={() => onChange(values.filter((item) => item !== value))}>
                ×
              </button>
            ) : null}
          </span>
        ))}
        {values.length === 0 ? <span className="sk-muted">None</span> : null}
      </div>
      {Object.entries(problems ?? {}).map(([value, problem]) => (
        <p key={value} className="sk-err" role="alert">{`“${value}”: ${problem}`}</p>
      ))}
      {!disabled ? (
        <div className="sk-row">
          <input className="admin-users__toolbar-input" value={draft} aria-label={`Add to ${label}`}
            data-testid={testId ? `${testId}-input` : undefined}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} />
          <button type="button" className="admin-panel__action-btn" disabled={!draft.trim()} data-testid={testId ? `${testId}-add` : undefined}
            onClick={add}>Add</button>
        </div>
      ) : null}
    </div>
  );
}
