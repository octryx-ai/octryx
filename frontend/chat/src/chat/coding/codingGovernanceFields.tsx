// Labelled form fields of the Coding governance editors: JSON, text, select, checkboxes and known-value lists.
import { jsonFieldError, type JsonFieldKind } from "./codingGovernanceForm";

export function JsonField({
  label,
  help,
  value,
  kind,
  onChange,
}: {
  label: string;
  help: string;
  value: string;
  kind: JsonFieldKind;
  onChange: (value: string) => void;
}) {
  const error = jsonFieldError(value, kind);
  return (
    <label className={`coding-policy-editor__field coding-gov-field ${error ? "is-invalid" : ""}`}>
      <span>{label}</span>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} spellCheck={false} aria-invalid={Boolean(error)} />
      <small className="coding-gov-help">{help}</small>
      {error ? <small className="coding-gov-error">{error}</small> : null}
    </label>
  );
}

export function TextField({
  label,
  value,
  onChange,
  help,
  placeholder,
  required = false,
  multiline = false,
  listId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  help?: string;
  placeholder?: string;
  required?: boolean;
  multiline?: boolean;
  listId?: string;
}) {
  return (
    <label className="coding-policy-editor__field coding-gov-field">
      <span>
        {label}
        {required ? <b className="coding-gov-required" aria-hidden="true"> *</b> : null}
      </span>
      {multiline ? (
        <textarea className="coding-gov-plain" value={value} placeholder={placeholder} required={required}
          onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input value={value} placeholder={placeholder} required={required} list={listId}
          onChange={(event) => onChange(event.target.value)} />
      )}
      {help ? <small className="coding-gov-help">{help}</small> : null}
    </label>
  );
}

export function SelectField({
  label,
  value,
  options,
  onChange,
  help,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
  help?: string;
}) {
  return (
    <label className="coding-policy-editor__field coding-gov-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value || "empty"} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {help ? <small className="coding-gov-help">{help}</small> : null}
    </label>
  );
}

export function CheckboxField({ label, checked, onChange, help }: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  help?: string;
}) {
  return (
    <label className="coding-gov-checkbox">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
      {help ? <small className="coding-gov-help">{help}</small> : null}
    </label>
  );
}

export function CheckboxGroup({ legend, help, options, isChecked, onToggle }: {
  legend: string;
  help?: string;
  options: Array<{ value: string; label: string }>;
  isChecked: (value: string) => boolean;
  onToggle: (value: string, checked: boolean) => void;
}) {
  return (
    <fieldset className="coding-gov-checkboxes">
      <legend>{legend}</legend>
      {options.map((option) => (
        <CheckboxField key={option.value} label={option.label} checked={isChecked(option.value)}
          onChange={(checked) => onToggle(option.value, checked)} />
      ))}
      {help ? <small className="coding-gov-help">{help}</small> : null}
    </fieldset>
  );
}

export function KnownValues({ id, values }: { id: string; values: string[] }) {
  return (
    <datalist id={id}>
      {values.map((value) => (
        <option key={value} value={value} />
      ))}
    </datalist>
  );
}
