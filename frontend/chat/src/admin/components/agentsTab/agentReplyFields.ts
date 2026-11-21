// Output format field types, limits, type labels and the empty field and format of an agent.
export type ReplyPrimitive = "string" | "integer" | "number" | "boolean";

export type ReplyField = {
  /** Local row identity only; never sent. */
  key: string;
  name: string;
  type: ReplyPrimitive;
  list: boolean;
  required: boolean;
};

export type ReplyFormatMode = "text" | "json_object" | "unsupported";

export type ReplyFormatState = {
  mode: ReplyFormatMode;
  fields: ReplyField[];
  /** The saved value in canonical form ("absent" when there is none), to tell whether it changed. */
  baseline: string;
};

export type ReplyContract =
  | { kind: "text" }
  | {
      kind: "json_object";
      schema: {
        type: "object";
        properties: Record<
          string,
          | { type: ReplyPrimitive }
          | { type: "array"; items: { type: ReplyPrimitive } }
        >;
        required: string[];
      };
    };

export const FIELD_NAME_PATTERN = /^[a-z][A-Za-z0-9_]{0,63}$/;
export const MAX_REPLY_FIELDS = 32;
export const MAX_REPLY_CONTRACT_BYTES = 16 * 1024;
export const PRIMITIVES: readonly ReplyPrimitive[] = [
  "string",
  "integer",
  "number",
  "boolean",
];
export const ABSENT = "absent";
export const UNSUPPORTED = "unsupported";

export const PRIMITIVE_LABELS: Record<ReplyPrimitive, string> = {
  string: "Text",
  integer: "Whole number",
  number: "Number",
  boolean: "Yes/no",
};

// List labels are plural and match the flow builder ("List of texts", "List of numbers").
const LIST_LABELS: Record<ReplyPrimitive, string> = {
  string: "List of texts",
  integer: "List of whole numbers",
  number: "List of numbers",
  boolean: "List of yes/no values",
};

export const FIELD_TYPE_OPTIONS: { value: string; label: string }[] = [
  ...PRIMITIVES.map((type) => ({ value: type, label: PRIMITIVE_LABELS[type] })),
  ...PRIMITIVES.map((type) => ({
    value: `list:${type}`,
    label: LIST_LABELS[type],
  })),
];

export function fieldTypeValue(
  field: Pick<ReplyField, "type" | "list">,
): string {
  return field.list ? `list:${field.type}` : field.type;
}

export function fieldTypeFromValue(
  value: string,
): Pick<ReplyField, "type" | "list"> {
  const list = value.startsWith("list:");
  const type = (list ? value.slice(5) : value) as ReplyPrimitive;
  return { type: PRIMITIVES.includes(type) ? type : "string", list };
}

export function fieldTypeLabel(
  field: Pick<ReplyField, "type" | "list">,
): string {
  return (
    FIELD_TYPE_OPTIONS.find((option) => option.value === fieldTypeValue(field))
      ?.label ?? "Text"
  );
}

let keySeed = 0;
export function newReplyField(): ReplyField {
  keySeed += 1;
  return {
    key: `reply-field-${keySeed}`,
    name: "",
    type: "string",
    list: false,
    required: true,
  };
}

export function defaultReplyFormat(): ReplyFormatState {
  return { mode: "text", fields: [], baseline: ABSENT };
}
