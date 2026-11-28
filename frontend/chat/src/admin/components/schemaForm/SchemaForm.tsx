import { useId, useMemo } from "react";

import "./schemaForm.css";
import { SchemaObjectBody } from "./SchemaObjectFields";
import { SchemaFormContext, type SchemaFormContextValue } from "./schemaFormContext";
import type { SchemaFormProps } from "./schemaFormTypes";
import { normalizeField } from "./schemaResolve";
import { clientFieldErrors, mergeErrors, orphanErrors } from "./schemaValidate";

export function SchemaForm({
  schema,
  value,
  onChange,
  errors,
  disabled = false,
  hiddenFields = [],
  renderField,
  idPrefix,
  clientValidation = true,
}: SchemaFormProps) {
  const generatedId = useId();
  const prefix = idPrefix ?? `schema-form-${generatedId.replace(/[^A-Za-z0-9_-]/g, "")}`;
  const rootObject = useMemo(() => normalizeField(schema, schema).schema, [schema]);
  const merged = useMemo(
    () => mergeErrors(errors, clientValidation ? clientFieldErrors(schema, schema, value) : undefined),
    [errors, clientValidation, schema, value],
  );
  const context = useMemo<SchemaFormContextValue>(
    () => ({ root: schema, errors: merged, disabled, idPrefix: prefix, renderField }),
    [schema, merged, disabled, prefix, renderField],
  );
  const unplaced = orphanErrors(rootObject, merged, hiddenFields);
  return (
    <SchemaFormContext.Provider value={context}>
      <div className="schema-form" aria-disabled={disabled || undefined}>
        {unplaced.length ? (
          <ul className="schema-form__summary" role="alert">
            {unplaced.map(([pointer, message]) => (
              <li key={`${pointer}:${message}`}>{pointer ? `${pointer}: ${message}` : message}</li>
            ))}
          </ul>
        ) : null}
        <SchemaObjectBody pointer="" schema={rootObject} value={value} onChange={onChange} hidden={hiddenFields} />
      </div>
    </SchemaFormContext.Provider>
  );
}
