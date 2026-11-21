// Labelled text input, labelled select and on/off toggle row shared by the repository forms.
export type FieldOption = [value: string, label: string];

type FieldProps = { id: string; label: string; value: string; onChange: (value: string) => void };

export function FormTextField({ id, label, value, onChange, placeholder }: FieldProps & { placeholder: string }) {
  return (
    <div className="admin-form-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        className="connector-field__input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

export function FormSelectField({ id, label, value, onChange, options }: FieldProps & { options: FieldOption[] }) {
  return (
    <div className="admin-form-field">
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        className="connector-field__input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>{optionLabel}</option>
        ))}
      </select>
    </div>
  );
}

export function FormToggleRow({ on, title, text, ariaLabel, onToggle }: {
  on: boolean;
  title: string;
  text: string;
  ariaLabel: string;
  onToggle: () => void;
}) {
  return (
    <div className="admin-form-toggle-row">
      <div className="admin-form-toggle-copy">
        <strong>{title}</strong>
        <span>{text}</span>
      </div>
      <button
        type="button"
        className={`admin-panel__toggle ${on ? "admin-panel__toggle--on" : "admin-panel__toggle--off"}`}
        onClick={onToggle}
        aria-label={ariaLabel}
      >
        <span />
      </button>
    </div>
  );
}
