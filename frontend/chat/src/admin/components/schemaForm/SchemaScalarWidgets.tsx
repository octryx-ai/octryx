import { useState } from "react";

import { useSchemaFormContext } from "./schemaFormContext";
import type { WidgetProps } from "./SchemaField";
import { controlClass, numberInputMax, numberInputMin, parseNumberInput, textInputValue } from "./schemaWidgets";

function ariaProps(props: WidgetProps) {
  return {
    id: props.id,
    "aria-describedby": props.describedBy,
    "aria-invalid": props.invalid || undefined,
    "aria-required": props.model.required || undefined,
  };
}

function formatJson(value: unknown): string {
  return value === undefined ? "" : JSON.stringify(value, null, 2);
}

function TextWidget(props: WidgetProps) {
  const { disabled } = useSchemaFormContext();
  const { model, value, onChange } = props;
  const text = typeof value === "string" ? value : value === undefined ? "" : String(value);
  const maxLength = typeof model.schema.maxLength === "number" ? model.schema.maxLength : undefined;
  if (model.widget === "textarea") {
    return (
      <textarea
        {...ariaProps(props)}
        className={controlClass(props, "schema-form__textarea")}
        value={text}
        maxLength={maxLength}
        placeholder={model.placeholder}
        disabled={disabled}
        rows={4}
        onChange={(event) => onChange(textInputValue(event.target.value))}
      />
    );
  }
  return (
    <input
      {...ariaProps(props)}
      type="text"
      className={controlClass(props)}
      value={text}
      maxLength={maxLength}
      placeholder={model.placeholder}
      disabled={disabled}
      spellCheck={model.mono ? false : undefined}
      onChange={(event) => onChange(textInputValue(event.target.value))}
    />
  );
}

function NumberWidget(props: WidgetProps) {
  const { disabled } = useSchemaFormContext();
  const [draft, setDraft] = useState<string | null>(null);
  const { model, value, onChange } = props;
  const shown = draft ?? (typeof value === "number" ? String(value) : "");
  return (
    <input
      {...ariaProps(props)}
      type="number"
      inputMode={model.kind === "integer" ? "numeric" : "decimal"}
      className={controlClass(props)}
      value={shown}
      step={model.kind === "integer" ? 1 : "any"}
      min={numberInputMin(model.schema)}
      max={numberInputMax(model.schema)}
      placeholder={model.placeholder}
      disabled={disabled}
      onChange={(event) => {
        setDraft(event.target.value);
        onChange(parseNumberInput(event.target.value));
      }}
      onBlur={() => setDraft(null)}
    />
  );
}

function CheckboxWidget(props: WidgetProps) {
  const { disabled } = useSchemaFormContext();
  const { model, value, onChange } = props;
  const fallback = typeof model.schema.default === "boolean" ? model.schema.default : false;
  const checked = typeof value === "boolean" ? value : fallback;
  return (
    <input
      {...ariaProps(props)}
      type="checkbox"
      className="schema-form__checkbox"
      checked={checked}
      disabled={disabled}
      onChange={(event) => {
        const next = event.target.checked;
        // Omit the key when the new state equals the schema default (or false without one).
        onChange(next === fallback && !model.required ? undefined : next);
      }}
    />
  );
}

function BooleanSelectWidget(props: WidgetProps) {
  const { disabled } = useSchemaFormContext();
  const { value, onChange } = props;
  const selected = value === true ? "true" : value === false ? "false" : "";
  return (
    <select
      {...ariaProps(props)}
      className={controlClass(props)}
      value={selected}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value === "true")}
    >
      <option value="">Select…</option>
      <option value="true">Yes</option>
      <option value="false">No</option>
    </select>
  );
}

function EnumWidget(props: WidgetProps) {
  const { disabled } = useSchemaFormContext();
  const { model, value, onChange } = props;
  const options = Array.isArray(model.schema.enum) ? model.schema.enum : [];
  const index = options.findIndex((option) => option === value);
  const unknownValue = value !== undefined && index < 0;
  return (
    <select
      {...ariaProps(props)}
      className={controlClass(props)}
      value={unknownValue ? "unknown" : index < 0 ? "" : String(index)}
      disabled={disabled}
      onChange={(event) => {
        const raw = event.target.value;
        if (raw === "unknown") return;
        onChange(raw === "" ? undefined : options[Number(raw)]);
      }}
    >
      <option value="">{model.required ? "Select…" : "Not set"}</option>
      {unknownValue ? <option value="unknown">{`${JSON.stringify(value)} (not allowed)`}</option> : null}
      {options.map((option, optionIndex) => (
        <option key={JSON.stringify(option)} value={String(optionIndex)}>
          {typeof option === "string" ? option : JSON.stringify(option)}
        </option>
      ))}
    </select>
  );
}

function ConstWidget(props: WidgetProps) {
  const constant = props.model.schema.const;
  return (
    <input
      {...ariaProps(props)}
      type="text"
      readOnly
      className={controlClass(props, "schema-form__control--readonly schema-form__control--mono")}
      value={typeof constant === "string" ? constant : JSON.stringify(constant)}
    />
  );
}

function JsonWidget(props: WidgetProps) {
  const { disabled } = useSchemaFormContext();
  const [draft, setDraft] = useState<string | null>(null);
  const [parseError, setParseError] = useState(false);
  const { value, onChange } = props;
  return (
    <>
      <textarea
        {...ariaProps(props)}
        aria-invalid={props.invalid || parseError || undefined}
        className={controlClass(props, "schema-form__textarea schema-form__control--mono")}
        value={draft ?? formatJson(value)}
        placeholder="JSON value"
        disabled={disabled}
        rows={3}
        spellCheck={false}
        onChange={(event) => {
          const text = event.target.value;
          setDraft(text);
          if (!text.trim()) {
            setParseError(false);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(text));
            setParseError(false);
          } catch {
            setParseError(true);
          }
        }}
        onBlur={() => {
          if (!parseError) setDraft(null);
        }}
      />
      {parseError ? <p className="schema-form__error">Invalid JSON; the last valid value is kept.</p> : null}
    </>
  );
}

function UnsupportedWidget(props: WidgetProps) {
  return (
    <div className="schema-form__unsupported" id={props.id} aria-describedby={props.describedBy}>
      <p className="schema-form__help">Unsupported field type; shown read-only.</p>
      <pre className="schema-form__preview">{formatJson(props.value ?? null)}</pre>
    </div>
  );
}

export function SchemaScalarWidget(props: WidgetProps) {
  switch (props.model.widget) {
    case "text":
    case "textarea":
      return <TextWidget {...props} />;
    case "number":
      return <NumberWidget {...props} />;
    case "checkbox":
      return <CheckboxWidget {...props} />;
    case "boolean-select":
      return <BooleanSelectWidget {...props} />;
    case "select":
      return <EnumWidget {...props} />;
    case "const":
      return <ConstWidget {...props} />;
    case "json":
      return <JsonWidget {...props} />;
    default:
      return <UnsupportedWidget {...props} />;
  }
}
