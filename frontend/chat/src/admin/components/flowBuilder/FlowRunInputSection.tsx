import { useId } from "react";
import type { FlowDefinitionJson } from "./flowBuilderTypes";
import {
  extraInputKeys,
  inputFieldText,
  parseInputObject,
  triggerInputFields,
  withInputFieldValue,
  type FlowInputField,
} from "./flowRunInput";

type FlowRunInputSectionProps = {
  definition: FlowDefinitionJson;
  inputJson: string;
  onInputChange: (value: string) => void;
};

function GuidedField({
  field,
  input,
  disabled,
  onChange,
}: {
  field: FlowInputField;
  input: Record<string, unknown>;
  disabled: boolean;
  onChange: (value: string | boolean) => void;
}) {
  const id = useId();
  if (field.type === "boolean") {
    return (
      <label className="flow-run-panel__check" htmlFor={id}>
        <input id={id} type="checkbox" checked={input[field.name] === true} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />
        <span>{field.label}</span>
      </label>
    );
  }
  return (
    <label className="admin-panel__field flow-run-panel__field" htmlFor={id}>
      <span>{field.label}</span>
      {field.type === "string" ? (
        <textarea id={id} rows={2} value={inputFieldText(input, field)} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input
          id={id}
          type="number"
          step={field.type === "integer" ? 1 : "any"}
          value={inputFieldText(input, field)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      <small>{field.name} · {field.type}</small>
    </label>
  );
}

// Test input first: labelled fields from the trigger's flat output schema, and the raw JSON
// (always what is sent) under "Advanced: raw input".
export function FlowRunInputSection({ definition, inputJson, onInputChange }: FlowRunInputSectionProps) {
  const fields = triggerInputFields(definition);
  const input = parseInputObject(inputJson);
  const extras = fields && input ? extraInputKeys(input, fields) : [];
  return (
    <section className="flow-run-panel__input" aria-label="Test input">
      <span className="admin-panel__section-title">Test input</span>
      {fields ? (
        <div className="flow-run-panel__fields">
          {fields.map((field) => (
            <GuidedField
              key={field.name}
              field={field}
              input={input ?? {}}
              disabled={!input}
              onChange={(value) => input && onInputChange(withInputFieldValue(input, field, value))}
            />
          ))}
        </div>
      ) : (
        <p className="admin-panel__hint">The trigger has no flat input schema, so enter the input as JSON below.</p>
      )}
      {fields && !input ? (
        <p className="admin-panel__hint" role="alert">The raw input is not a valid JSON object. Fix it under Advanced: raw input.</p>
      ) : null}
      {extras.length ? (
        <p className="admin-panel__hint">Also sent: {extras.join(", ")} (edit under Advanced: raw input).</p>
      ) : null}
      <details className="flow-run-panel__advanced" open={!fields}>
        <summary>Advanced: raw input</summary>
        <textarea
          className="flow-builder__trace-input"
          aria-label="Raw test input (JSON object)"
          value={inputJson}
          rows={6}
          spellCheck={false}
          onChange={(event) => onInputChange(event.target.value)}
        />
      </details>
    </section>
  );
}
