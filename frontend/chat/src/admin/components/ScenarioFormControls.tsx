// Scenario form: the multi-select pills, toggle rows, section blocks and the raw JSON accordion.
import React from "react";
import type { Dispatch, SetStateAction } from "react";

// ─── Multi-select pill helper ───────────────────────────────────────────────

type MultiSelectOption = { value: string; label: string; hint?: string };

type MultiSelectProps<T extends MultiSelectOption> = {
  label: string;
  options: readonly T[];
  selected: string[];
  onChange: (selected: string[]) => void;
  hint?: string;
};

export function MultiSelect<T extends MultiSelectOption>({
  label,
  options,
  selected,
  onChange,
  hint,
}: MultiSelectProps<T>) {
  const toggle = (value: string) => {
    onChange(
      selected.includes(value)
        ? selected.filter((s) => s !== value)
        : [...selected, value],
    );
  };

  return (
    <div className="admin-form-field">
      <label
        style={{
          fontSize: "var(--ds-text-xs)",
          fontWeight: 600,
          marginBottom: "0.25rem",
        }}
      >
        {label}
      </label>
      {hint && <span className="admin-form-help">{hint}</span>}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.4rem",
          marginTop: "0.35rem",
        }}
      >
        {options.map((opt) => {
          const isSelected = selected.includes(opt.value);
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => toggle(opt.value)}
              title={opt.hint}
              style={{
                background: isSelected
                  ? "rgba(74,222,128,0.15)"
                  : "rgba(255,255,255,0.04)",
                border: `1px solid ${isSelected ? "rgba(74,222,128,0.4)" : "var(--border-soft)"}`,
                borderRadius: "var(--ds-radius-md)",
                padding: "0.2rem 0.55rem",
                fontSize: "var(--ds-text-xs)",
                color: isSelected ? "var(--status-active)" : "var(--text-secondary)",
                cursor: "pointer",
                transition: "all 0.15s",
              }}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
      {selected.length > 0 && (
        <div
          style={{
            marginTop: "0.25rem",
            fontSize: "var(--ds-text-2xs)",
            color: "var(--text-muted)",
          }}
        >
          Selected: {selected.join(", ")}
        </div>
      )}
    </div>
  );
}

// ─── Toggle row ─────────────────────────────────────────────────────────────

export function ToggleRow({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0.35rem 0",
      }}
    >
      <div>
        <div style={{ fontSize: "var(--ds-text-xs)", fontWeight: 500 }}>{label}</div>
        <div style={{ fontSize: "var(--ds-text-2xs)", color: "var(--text-muted)" }}>
          {hint}
        </div>
      </div>
      <button
        type="button"
        className={`admin-panel__toggle ${value ? "admin-panel__toggle--on" : "admin-panel__toggle--off"}`}
        onClick={() => onChange(!value)}
        aria-label={label}
      >
        <span />
      </button>
    </div>
  );
}

// ─── Section block ───────────────────────────────────────────────────────────

export function SectionBlock({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        border: "1px solid var(--border-soft)",
        borderRadius: "var(--ds-radius-md)",
        overflow: "hidden",
        marginBottom: "0.7rem",
      }}
    >
      <div
        style={{
          background: "rgba(255,255,255,0.04)",
          padding: "0.5rem 0.9rem",
          borderBottom: "1px solid var(--border-soft)",
          fontSize: "var(--ds-text-xs)",
          fontWeight: 600,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: "var(--text-muted)",
        }}
      >
        {title}
      </div>
      <div
        style={{
          padding: "0.8rem 0.9rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.6rem",
        }}
      >
        {children}
      </div>
    </div>
  );
}

// ─── Raw JSON accordion ─────────────────────────────────────────────────────

type RawJsonToggleProps = {
  label: string;
  jsonValue: string;
  onChange: Dispatch<SetStateAction<string>>;
};

function RawJsonToggle({ label, jsonValue, onChange }: RawJsonToggleProps) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="admin-form-field">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <label
          style={{
            fontSize: "var(--ds-text-xs)",
            fontWeight: 600,
            marginBottom: "0.25rem",
          }}
        >
          {label}
        </label>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          style={{
            background: "none",
            border: "1px solid var(--border-soft)",
            borderRadius: "var(--ds-radius-sm)",
            padding: "0.1rem 0.5rem",
            fontSize: "var(--ds-text-2xs)",
            color: "var(--text-muted)",
            cursor: "pointer",
          }}
        >
          {open ? "Hide JSON" : "Edit raw JSON"}
        </button>
      </div>
      {open ? (
        <textarea
          className="connector-field__input connector-field__input--textarea"
          value={jsonValue}
          onChange={(e) => onChange(e.target.value)}
          rows={6}
          spellCheck={false}
        />
      ) : null}
    </div>
  );
}
