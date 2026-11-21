import type { ReactNode } from "react";

/** One JSON Schema node (draft 2020-12 / Pydantic v2 shape). */
export type JsonSchema = { [key: string]: unknown };

/** Error messages keyed by JSON pointer relative to the form value, e.g. "/loop/maxIterations". */
export type SchemaFormErrors = Record<string, string[]>;

export interface SchemaFieldRenderArgs {
  /** JSON pointer of the field relative to the form value. */
  pointer: string;
  /** The field schema with `$ref` resolved and a nullable `anyOf [X, null]` unwrapped to X. */
  schema: JsonSchema;
  /** The field's `x-ui` hints (empty object when none). */
  ui: Record<string, unknown>;
  value: unknown;
  /** Immutable update of this field; `undefined` removes the key. */
  onChange: (next: unknown) => void;
  disabled: boolean;
  /** DOM id the form's <label> points at; bind it to the host control. */
  id: string;
  /** Space-separated ids of help/error text; pass to `aria-describedby`. */
  describedBy: string | undefined;
  /** Human label of the field. */
  label: string;
  required: boolean;
  /** Merged server + client messages for exactly this pointer. */
  errors: string[];
}

/**
 * Host override for one field's control. Return `undefined` to fall back to
 * the default widget. The form keeps rendering the label, help and errors.
 */
export type SchemaFieldRenderer = (args: SchemaFieldRenderArgs) => ReactNode | undefined;

export interface SchemaFormProps {
  /** Root schema; may contain `$defs`, `$ref` resolves against it. */
  schema: JsonSchema;
  value: Record<string, unknown>;
  /** Immutable updates; unset optional fields are omitted, never sent as null or "". */
  onChange: (next: Record<string, unknown>) => void;
  /** Server finding paths already mapped to form pointers by the caller. */
  errors?: SchemaFormErrors;
  /** Read-only (e.g. a published revision). */
  disabled?: boolean;
  /** Top-level property names the host renders elsewhere (e.g. "kind", edge fields). */
  hiddenFields?: string[];
  /** Host override for x-ui widgets the host owns (edges, reference pickers). */
  renderField?: SchemaFieldRenderer;
  idPrefix?: string;
  /** Run the cheap local checks (`clientFieldErrors`) and show them inline. Default true. */
  clientValidation?: boolean;
}

/** Structural classification of a (resolved, unwrapped) schema node. */
export type SchemaKind =
  | "const"
  | "enum"
  | "string"
  | "number"
  | "integer"
  | "boolean"
  | "object"
  | "map"
  | "array"
  | "union"
  | "any"
  | "unsupported";

/** Every known `x-ui.widget` value, and what the form does by default. */
export const SCHEMA_FORM_UI_WIDGETS = {
  textarea: "multi-line text",
  duration: "text with duration hint (number + s/m/h/d)",
  edge: "node id text input (host renders the edge picker)",
  edges: "list of node ids (host renders the multi-edge picker)",
  "edge-map": "key -> node id map (host renders the branch editor)",
  node: "node id text input (host renders the node picker)",
  nodes: "list of node ids",
  resource: "resource name text input (host renders the reference picker)",
  resources: "list of resource names",
  schema: "schema name text input",
  discriminator: "<node>.<field> text input",
  roles: "list of role names",
  "state-keys": "list of state keys",
} as const;

export type SchemaFormUiWidget = keyof typeof SCHEMA_FORM_UI_WIDGETS;
