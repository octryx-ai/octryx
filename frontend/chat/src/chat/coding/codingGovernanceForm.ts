// Shared form helpers for the Coding governance editors (Policies, Pipelines,
// CI/CD; audit IDs 28–31). Parsing keeps the editors' existing
// semantics: empty text means an empty object/array, objects reject arrays, and
// object lists drop non-object entries.
export type JsonFieldKind = "object" | "array" | "objectList";

// Default the backend stores when review_status is empty (coding pipelines,
// technology baselines); the field itself stays free text.
export const DEFAULT_REVIEW_STATUS = "needs_review";

export function jsonFieldError(value: string, kind: JsonFieldKind): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value.trim() || (kind === "object" ? "{}" : "[]"));
  } catch {
    return "Not valid JSON. Check quotes, commas and brackets.";
  }
  if (kind === "object") {
    return isPlainObject(parsed) ? null : "Must be a JSON object, for example {}.";
  }
  return Array.isArray(parsed) ? null : "Must be a JSON list, for example [].";
}

export function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed = parseJson(value, label, "{}");
  if (!isPlainObject(parsed)) throw new Error(`${label} must be an object`);
  return parsed;
}

export function parseJsonArray(value: string, label: string): unknown[] {
  const parsed = parseJson(value, label, "[]");
  if (!Array.isArray(parsed)) throw new Error(`${label} must be an array`);
  return parsed;
}

export function parseJsonObjectList(value: string, label: string): Array<Record<string, unknown>> {
  return parseJsonArray(value, label).filter(isPlainObject);
}

export function stringifyJson(value: unknown, fallback: "{}" | "[]"): string {
  return JSON.stringify(value ?? JSON.parse(fallback), null, 2);
}

export function splitValues(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export function listHasValue(text: string, value: string): boolean {
  return splitValues(text).includes(value);
}

// Toggles one value in a newline list and keeps unknown entries and their order.
export function toggleListValue(text: string, value: string, enabled: boolean): string {
  const values = splitValues(text).filter((entry) => entry !== value);
  return (enabled ? [...values, value] : values).join("\n");
}

// Values the backend stores as free text but that have a known default; the
// editor offers the default plus values already in use, never invented ones.
export function knownValueOptions(defaultValue: string, observed: Array<string | null | undefined>): string[] {
  const values = [defaultValue, ...observed].map((entry) => (entry || "").trim()).filter(Boolean);
  return Array.from(new Set(values));
}

export function hasJsonErrors(fields: Array<[string, JsonFieldKind]>): boolean {
  return fields.some(([value, kind]) => jsonFieldError(value, kind) !== null);
}

export function humanize(value: string): string {
  const text = value.replaceAll("_", " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

function parseJson(value: string, label: string, fallback: string): unknown {
  try {
    return JSON.parse(value.trim() || fallback);
  } catch {
    throw new Error(`${label} is not valid JSON`);
  }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
