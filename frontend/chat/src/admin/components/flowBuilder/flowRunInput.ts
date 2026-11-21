// Guided test input: labelled fields generated from the trigger's output schema when that
// schema is a flat object of primitive types. The raw JSON text stays the single source of
// truth (it is also what test cases and approvals send); fields read from and write into it.
import type { FlowDefinitionJson } from "./flowBuilderTypes";

export type FlowInputFieldType = "string" | "number" | "integer" | "boolean";

export type FlowInputField = { name: string; type: FlowInputFieldType; label: string };

const PRIMITIVE_TYPES = new Set<string>(["string", "number", "integer", "boolean"]);

function fieldLabel(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : name;
}

// Null when there is no single trigger or its schema is not a flat object of primitives:
// the editor then offers only the raw JSON input instead of guessing a form.
export function triggerInputFields(definition: FlowDefinitionJson): FlowInputField[] | null {
  const triggers = (definition.nodes ?? []).filter((node) => node.type === "trigger");
  if (triggers.length !== 1) return null;
  const schema = triggers[0].output_schema;
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) return null;
  const entries = Object.entries(schema);
  if (!entries.length) return null;
  const fields: FlowInputField[] = [];
  for (const [name, type] of entries) {
    if (typeof type !== "string" || !PRIMITIVE_TYPES.has(type)) return null;
    fields.push({ name, type: type as FlowInputFieldType, label: fieldLabel(name) });
  }
  return fields;
}

export function parseInputObject(inputJson: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(inputJson) as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export function inputFieldText(input: Record<string, unknown>, field: FlowInputField): string {
  const value = input[field.name];
  if (value === undefined || value === null) return "";
  return typeof value === "string" ? value : String(value);
}

// Returns the new raw JSON text after a field edit. Numbers are stored as numbers; an empty
// number field removes the key rather than sending an invalid value.
export function withInputFieldValue(
  input: Record<string, unknown>,
  field: FlowInputField,
  value: string | boolean,
): string {
  const next = { ...input };
  if (field.type === "boolean") {
    next[field.name] = Boolean(value);
  } else if (field.type === "number" || field.type === "integer") {
    const text = String(value).trim();
    const parsed = Number(text);
    if (!text || !Number.isFinite(parsed)) delete next[field.name];
    else next[field.name] = field.type === "integer" ? Math.trunc(parsed) : parsed;
  } else {
    next[field.name] = String(value);
  }
  return JSON.stringify(next, null, 2);
}

// Keys in the raw input the guided form does not show; they are still sent, so the form names them.
export function extraInputKeys(input: Record<string, unknown>, fields: FlowInputField[]): string[] {
  const known = new Set(fields.map((field) => field.name));
  return Object.keys(input).filter((key) => !known.has(key));
}
