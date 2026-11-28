import { splitPointer } from "./schemaPointer";
import type { JsonSchema, SchemaKind } from "./schemaFormTypes";

const MAX_REF_DEPTH = 32;
const ANNOTATION_KEYS = new Set(["anyOf", "oneOf", "type"]);

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function lookupRef(root: JsonSchema, ref: string): JsonSchema | null {
  if (!ref.startsWith("#")) return null;
  let current: unknown = root;
  for (const segment of splitPointer(ref.slice(1))) {
    if (!isRecord(current)) return null;
    current = current[segment];
  }
  return isRecord(current) ? current : null;
}

/** Sibling keywords next to `$ref` override the target's; an unresolvable ref stays unchanged (unsupported). */
export function resolveRef(root: JsonSchema, schema: JsonSchema): JsonSchema {
  let current = schema;
  for (let depth = 0; depth < MAX_REF_DEPTH; depth += 1) {
    const ref = current.$ref;
    if (typeof ref !== "string") return current;
    const target = lookupRef(root, ref);
    if (!target) return current;
    const { $ref: _ignored, ...siblings } = current;
    current = { ...target, ...siblings };
  }
  return current;
}

function isNullSchema(schema: unknown): boolean {
  return isRecord(schema) && schema.type === "null" && Object.keys(schema).length === 1;
}

export interface NormalizedField {
  schema: JsonSchema;
  nullable: boolean;
}

/** Unwraps the Pydantic optional shape `anyOf: [X, {type: null}]` to X; outer annotations win. */
export function normalizeField(root: JsonSchema, schema: JsonSchema): NormalizedField {
  const resolved = resolveRef(root, schema);
  const variants = Array.isArray(resolved.anyOf) ? resolved.anyOf : Array.isArray(resolved.oneOf) ? resolved.oneOf : null;
  if (variants && !resolved.discriminator) {
    const nonNull = variants.filter((variant) => !isNullSchema(variant));
    if (nonNull.length === 1 && nonNull.length < variants.length && isRecord(nonNull[0])) {
      const outer = Object.fromEntries(Object.entries(resolved).filter(([key]) => !ANNOTATION_KEYS.has(key)));
      const inner = resolveRef(root, nonNull[0]);
      return { schema: { ...inner, ...outer }, nullable: true };
    }
  }
  if (Array.isArray(resolved.type) && resolved.type.includes("null")) {
    const types = resolved.type.filter((type) => type !== "null");
    if (types.length === 1) return { schema: { ...resolved, type: types[0] }, nullable: true };
  }
  return { schema: resolved, nullable: false };
}

export function unionVariants(schema: JsonSchema): unknown[] | null {
  if (Array.isArray(schema.oneOf)) return schema.oneOf;
  if (Array.isArray(schema.anyOf)) return schema.anyOf;
  return null;
}

export function mapValueSchema(schema: JsonSchema): JsonSchema | null {
  if (isRecord(schema.additionalProperties)) return schema.additionalProperties;
  if (isRecord(schema.patternProperties)) {
    const values = Object.values(schema.patternProperties).filter(isRecord);
    if (values.length === 1) return values[0];
  }
  return null;
}

export function classifySchema(schema: JsonSchema): SchemaKind {
  if ("const" in schema) return "const";
  if (Array.isArray(schema.enum)) return "enum";
  if (unionVariants(schema)) return "union";
  if (typeof schema.$ref === "string") return "unsupported";
  switch (schema.type) {
    case "string":
      return "string";
    case "integer":
      return "integer";
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "array":
      return isRecord(schema.items) ? "array" : "unsupported";
    case "object":
      if (isRecord(schema.properties)) return "object";
      if (mapValueSchema(schema)) return "map";
      return schema.additionalProperties === false ? "object" : "any";
    case undefined:
      return Object.keys(schema).every((key) => !isStructuralKeyword(key)) ? "any" : "unsupported";
    default:
      return "unsupported";
  }
}

const STRUCTURAL_KEYWORDS = new Set([
  "type", "properties", "items", "prefixItems", "allOf", "not", "if", "then", "else",
  "additionalProperties", "patternProperties", "dependentSchemas", "$ref", "$dynamicRef",
]);

function isStructuralKeyword(key: string): boolean {
  return STRUCTURAL_KEYWORDS.has(key);
}

export function uiHints(schema: JsonSchema): Record<string, unknown> {
  const ui = schema["x-ui"];
  return isRecord(ui) ? ui : {};
}

export function requiredSet(schema: JsonSchema): Set<string> {
  return new Set(Array.isArray(schema.required) ? schema.required.filter((key): key is string => typeof key === "string") : []);
}

export function fieldOrder(schema: JsonSchema): string[] {
  const properties = isRecord(schema.properties) ? Object.keys(schema.properties) : [];
  const required = requiredSet(schema);
  return [...properties.filter((key) => required.has(key)), ...properties.filter((key) => !required.has(key))];
}

export function humanizeKey(key: string): string {
  const words = key
    .replace(/[_-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length) return key;
  return words
    .map((word, index) => (index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : /^[A-Z0-9]+$/.test(word) ? word : word.toLowerCase()))
    .join(" ");
}

/** Label precedence: `x-ui.label`, then the humanized property key (Pydantic titles are ignored). */
export function fieldLabel(key: string, schema: JsonSchema): string {
  const label = uiHints(schema).label;
  return typeof label === "string" && label.trim() ? label : humanizeKey(key);
}

export function fieldDescription(schema: JsonSchema): string | undefined {
  const help = uiHints(schema).help;
  if (typeof help === "string" && help.trim()) return help;
  return typeof schema.description === "string" && schema.description.trim() ? schema.description : undefined;
}
