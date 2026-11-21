// Field model: which default widget renders a schema node, from schema keywords and x-ui only.
import { classifySchema, fieldDescription, fieldLabel, isRecord, normalizeField, uiHints } from "./schemaResolve";
import type { JsonSchema, SchemaKind } from "./schemaFormTypes";

export type SchemaWidget =
  | "text"
  | "textarea"
  | "number"
  | "checkbox"
  | "boolean-select"
  | "select"
  | "const"
  | "tags"
  | "checklist"
  | "items"
  | "object"
  | "map"
  | "union"
  | "json"
  | "unsupported";

/** Strings allowing more than this many characters get a textarea. */
export const TEXTAREA_MIN_MAX_LENGTH = 500;

const LIST_WIDGETS = new Set(["edges", "nodes", "resources", "roles", "state-keys"]);

const PLACEHOLDERS: Record<string, string> = {
  edge: "Node id",
  node: "Node id",
  resource: "Resource name",
  schema: "Schema name",
  discriminator: "node.field",
  duration: "e.g. 30s, 15m, 2h, 1d",
  edges: "Add node id",
  nodes: "Add node id",
  resources: "Add resource name",
  roles: "Add role",
  "state-keys": "Add state key",
};

export interface FieldModel {
  pointer: string;
  key: string;
  /** Resolved + nullable-unwrapped schema. */
  schema: JsonSchema;
  kind: SchemaKind;
  widget: SchemaWidget;
  ui: Record<string, unknown>;
  label: string;
  help: string | undefined;
  placeholder: string | undefined;
  required: boolean;
  nullable: boolean;
  /** Identifier-like values (references, keys) render in the mono font. */
  mono: boolean;
}

function isScalarKind(kind: SchemaKind): boolean {
  return kind === "string" || kind === "number" || kind === "integer";
}

export function selectWidget(root: JsonSchema, schema: JsonSchema, kind: SchemaKind, required: boolean): SchemaWidget {
  const widget = uiHints(schema).widget;
  switch (kind) {
    case "string": {
      const maxLength = typeof schema.maxLength === "number" ? schema.maxLength : undefined;
      if (widget === "textarea" || (maxLength !== undefined && maxLength > TEXTAREA_MIN_MAX_LENGTH)) return "textarea";
      return "text";
    }
    case "number":
    case "integer":
      return "number";
    case "boolean":
      return required && schema.default === undefined ? "boolean-select" : "checkbox";
    case "enum":
      return "select";
    case "const":
      return "const";
    case "object":
      return "object";
    case "map":
      return "map";
    case "union":
      return "union";
    case "any":
      return "json";
    case "array": {
      const items = normalizeField(root, schema.items as JsonSchema).schema;
      const itemKind = classifySchema(items);
      if (itemKind === "enum") return "checklist";
      if (isScalarKind(itemKind) || (typeof widget === "string" && LIST_WIDGETS.has(widget) && itemKind !== "object")) return "tags";
      return "items";
    }
    default:
      return "unsupported";
  }
}

/** Describe the field at `pointer` named `key` for rendering. */
export function describeField(root: JsonSchema, pointer: string, key: string, rawSchema: JsonSchema, required: boolean): FieldModel {
  const { schema, nullable } = normalizeField(root, rawSchema);
  const kind = classifySchema(schema);
  const ui = uiHints(schema);
  const widget = selectWidget(root, schema, kind, required);
  const hint = typeof ui.widget === "string" ? ui.widget : "";
  const explicitPlaceholder = typeof ui.placeholder === "string" ? ui.placeholder : undefined;
  const itemsPattern = isRecord(schema.items) ? schema.items.pattern : undefined;
  return {
    pointer,
    key,
    schema,
    kind,
    widget,
    ui,
    label: fieldLabel(key, schema),
    help: fieldDescription(schema),
    placeholder: explicitPlaceholder ?? PLACEHOLDERS[hint],
    required,
    nullable,
    mono: Boolean(hint && hint !== "textarea") || typeof schema.pattern === "string" || typeof itemsPattern === "string",
  };
}

/** Parse the text of a number input; empty or invalid input unsets the field. */
export function parseNumberInput(text: string): number | undefined {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : undefined;
}

/** Text inputs never write "": clearing the input unsets the field. */
export function textInputValue(text: string): string | undefined {
  return text === "" ? undefined : text;
}

/** HTML min attribute for a number field (exclusiveMinimum on integers becomes +1). */
export function numberInputMin(schema: JsonSchema): number | undefined {
  if (typeof schema.minimum === "number") return schema.minimum;
  if (typeof schema.exclusiveMinimum === "number") {
    return schema.type === "integer" ? schema.exclusiveMinimum + 1 : undefined;
  }
  return undefined;
}

export function numberInputMax(schema: JsonSchema): number | undefined {
  if (typeof schema.maximum === "number") return schema.maximum;
  if (typeof schema.exclusiveMaximum === "number") {
    return schema.type === "integer" ? schema.exclusiveMaximum - 1 : undefined;
  }
  return undefined;
}

/** An emptied optional list or map is omitted instead of written as []/{}. */
export function emptyCollectionValue<T extends unknown[] | Record<string, unknown>>(next: T, required: boolean): T | undefined {
  const empty = Array.isArray(next) ? next.length === 0 : Object.keys(next).length === 0;
  return empty && !required ? undefined : next;
}

/** Parse the add-input of a tag list; blank input adds nothing. */
export function parseTagInput(text: string, itemType: unknown): string | number | undefined {
  if (itemType === "number" || itemType === "integer") return parseNumberInput(text);
  const trimmed = text.trim();
  return trimmed ? trimmed : undefined;
}

function keyPatternMatches(pattern: string, key: string): boolean {
  try {
    return new RegExp(pattern, "u").test(key);
  } catch {
    return true;
  }
}

/** Why `key` cannot be added to a map field, or undefined when it can. */
export function mapKeyProblem(schema: JsonSchema, key: string, existing: string[]): string | undefined {
  if (existing.includes(key)) return "Key already exists";
  const names = isRecord(schema.propertyNames) ? schema.propertyNames : {};
  const length = [...key].length;
  if (typeof names.minLength === "number" && length < names.minLength) return `Key needs at least ${names.minLength} characters`;
  if (typeof names.maxLength === "number" && length > names.maxLength) return `Key allows at most ${names.maxLength} characters`;
  if (typeof names.pattern === "string" && !keyPatternMatches(names.pattern, key)) return `Key must match ${names.pattern}`;
  const patterns = isRecord(schema.patternProperties) ? Object.keys(schema.patternProperties) : [];
  if (patterns.length && !isRecord(schema.additionalProperties) && !patterns.some((pattern) => keyPatternMatches(pattern, key))) {
    return `Key must match ${patterns.join(" or ")}`;
  }
  return undefined;
}

/** Class list of a default control: the shared input geometry plus schema-form states. */
export function controlClass(props: { model: Pick<FieldModel, "mono">; invalid: boolean }, extra = ""): string {
  return [
    "admin-panel__form-input",
    "schema-form__control",
    props.model.mono ? "schema-form__control--mono" : "",
    props.invalid ? "schema-form__control--invalid" : "",
    extra,
  ]
    .filter(Boolean)
    .join(" ");
}

/** Label for use inside a phrase ("Add loop"); acronyms ("MCP servers") keep their case. */
export function inlineLabel(label: string): string {
  return /^[A-Z][A-Z0-9]/.test(label) ? label : label.charAt(0).toLowerCase() + label.slice(1);
}
