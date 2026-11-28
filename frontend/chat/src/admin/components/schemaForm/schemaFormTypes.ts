import type { ReactNode } from "react";

export type JsonSchema = { [key: string]: unknown };

export type SchemaFormErrors = Record<string, string[]>;

export interface SchemaFieldRenderArgs {
  pointer: string;
  schema: JsonSchema;
  ui: Record<string, unknown>;
  value: unknown;
  onChange: (next: unknown) => void;
  disabled: boolean;
  id: string;
  describedBy: string | undefined;
  label: string;
  required: boolean;
  errors: string[];
}

// Return undefined to fall back to the default widget.
export type SchemaFieldRenderer = (args: SchemaFieldRenderArgs) => ReactNode | undefined;

export interface SchemaFormProps {
  schema: JsonSchema;
  value: Record<string, unknown>;
  // Unset optional fields are omitted, never sent as null or "".
  onChange: (next: Record<string, unknown>) => void;
  errors?: SchemaFormErrors;
  disabled?: boolean;
  hiddenFields?: string[];
  renderField?: SchemaFieldRenderer;
  idPrefix?: string;
  clientValidation?: boolean;
}

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
