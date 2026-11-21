import { createContext, useContext } from "react";

import type { JsonSchema, SchemaFieldRenderer, SchemaFormErrors } from "./schemaFormTypes";

export interface SchemaFormContextValue {
  root: JsonSchema;
  errors: SchemaFormErrors;
  disabled: boolean;
  idPrefix: string;
  renderField?: SchemaFieldRenderer;
}

export const SchemaFormContext = createContext<SchemaFormContextValue | null>(null);

export function useSchemaFormContext(): SchemaFormContextValue {
  const value = useContext(SchemaFormContext);
  if (!value) throw new Error("Schema form fields must render inside <SchemaForm>.");
  return value;
}

/** Messages for `pointer` and, when `includeNested`, for every pointer below it. */
export function errorsAt(errors: SchemaFormErrors, pointer: string, includeNested = false): string[] {
  if (!includeNested) return errors[pointer] ?? [];
  const prefix = `${pointer}/`;
  return Object.entries(errors)
    .filter(([key]) => key === pointer || key.startsWith(prefix))
    .flatMap(([key, messages]) => (key === pointer ? messages : messages.map((message) => `${key.slice(pointer.length)}: ${message}`)));
}
