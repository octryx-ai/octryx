import type { ReactNode } from "react";

import { SchemaChecklistWidget, SchemaItemsWidget, SchemaMapWidget, SchemaTagsWidget } from "./SchemaCollectionWidgets";
import { SchemaObjectWidget, SchemaUnionWidget } from "./SchemaObjectFields";
import { SchemaScalarWidget } from "./SchemaScalarWidgets";
import { errorsAt, useSchemaFormContext } from "./schemaFormContext";
import type { JsonSchema } from "./schemaFormTypes";
import { fieldDomId } from "./schemaPointer";
import { describeField, type FieldModel, type SchemaWidget } from "./schemaWidgets";

export interface SchemaFieldProps {
  pointer: string;
  /** Property name (or item label); humanized unless `label` is given. */
  name: string;
  schema: JsonSchema;
  required: boolean;
  value: unknown;
  onChange: (next: unknown) => void;
  /** Verbatim label, e.g. a map key. */
  label?: string;
}

export interface WidgetProps {
  model: FieldModel;
  id: string;
  value: unknown;
  onChange: (next: unknown) => void;
  describedBy: string | undefined;
  invalid: boolean;
}

const GROUP_WIDGETS = new Set<SchemaWidget>(["object", "union", "items", "map", "checklist"]);
/** Widgets that show every message below their pointer (they render no nested fields). */
const NESTED_ERROR_WIDGETS = new Set<SchemaWidget>(["json", "unsupported", "tags", "checklist"]);

function DefaultWidget(props: WidgetProps): ReactNode {
  switch (props.model.widget) {
    case "object":
      return <SchemaObjectWidget {...props} />;
    case "union":
      return <SchemaUnionWidget {...props} />;
    case "tags":
      return <SchemaTagsWidget {...props} />;
    case "checklist":
      return <SchemaChecklistWidget {...props} />;
    case "items":
      return <SchemaItemsWidget {...props} />;
    case "map":
      return <SchemaMapWidget {...props} />;
    default:
      return <SchemaScalarWidget {...props} />;
  }
}

function FieldMessages({ id, help, messages }: { id: string; help?: string; messages: string[] }) {
  return (
    <>
      {help ? (
        <p id={`${id}-help`} className="schema-form__help">
          {help}
        </p>
      ) : null}
      {messages.length ? (
        <ul id={`${id}-error`} className="schema-form__error" role="alert">
          {messages.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

function RequiredMark({ required }: { required: boolean }) {
  return required ? (
    <span className="schema-form__required" aria-hidden="true">
      *
    </span>
  ) : null;
}

export function SchemaField({ pointer, name, schema, required, value, onChange, label }: SchemaFieldProps) {
  const context = useSchemaFormContext();
  const described = describeField(context.root, pointer, name, schema, required);
  const model = label ? { ...described, label } : described;
  const id = fieldDomId(context.idPrefix, pointer);
  const messages = errorsAt(context.errors, pointer, NESTED_ERROR_WIDGETS.has(model.widget));
  const describedBy = [model.help ? `${id}-help` : "", messages.length ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined;
  const invalid = messages.length > 0;
  const hostControl = context.renderField?.({
    pointer,
    schema: model.schema,
    ui: model.ui,
    value,
    onChange,
    disabled: context.disabled,
    id,
    describedBy,
    label: model.label,
    required,
    errors: messages,
  });
  const control = hostControl !== undefined ? hostControl : <DefaultWidget model={model} id={id} value={value} onChange={onChange} describedBy={describedBy} invalid={invalid} />;

  if (hostControl === undefined && GROUP_WIDGETS.has(model.widget)) {
    return (
      <fieldset className="schema-form__group" aria-describedby={describedBy} aria-invalid={invalid || undefined} data-pointer={pointer}>
        <legend className="schema-form__legend">
          {model.label}
          <RequiredMark required={required} />
        </legend>
        <FieldMessages id={id} help={model.help} messages={messages} />
        {control}
      </fieldset>
    );
  }
  if (hostControl === undefined && model.widget === "checkbox") {
    return (
      <div className="schema-form__field schema-form__field--inline" data-pointer={pointer}>
        <label className="schema-form__check">
          {control}
          <span className="schema-form__label">{model.label}</span>
        </label>
        <FieldMessages id={id} help={model.help} messages={messages} />
      </div>
    );
  }
  return (
    <div className="schema-form__field" data-pointer={pointer}>
      <label className="schema-form__label" htmlFor={id}>
        {model.label}
        <RequiredMark required={required} />
      </label>
      {control}
      <FieldMessages id={id} help={model.help} messages={messages} />
    </div>
  );
}
