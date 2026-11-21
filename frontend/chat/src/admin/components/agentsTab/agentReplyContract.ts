// Reads a saved output format contract into form state and builds a contract from fields.
import {
  FIELD_NAME_PATTERN,
  MAX_REPLY_FIELDS,
  PRIMITIVES,
  UNSUPPORTED,
  defaultReplyFormat,
  newReplyField,
  type ReplyContract,
  type ReplyField,
  type ReplyFormatState,
  type ReplyPrimitive,
} from "./agentReplyFields";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);
const hasExactKeys = (
  value: Record<string, unknown>,
  allowed: string[],
  required: string[],
) =>
  Object.keys(value).every((key) => allowed.includes(key)) &&
  required.every((key) => key in value);
const isPrimitive = (value: unknown): value is ReplyPrimitive =>
  PRIMITIVES.includes(value as ReplyPrimitive);

/** The saved fields, or null when the value is outside the contract this form can represent. */
function parseJsonObjectContract(
  value: Record<string, unknown>,
): ReplyField[] | null {
  if (
    !hasExactKeys(value, ["kind", "schema"], ["kind", "schema"]) ||
    !isRecord(value.schema)
  )
    return null;
  const schema = value.schema;
  if (
    !hasExactKeys(
      schema,
      ["type", "properties", "required"],
      ["type", "properties"],
    ) ||
    schema.type !== "object"
  ) {
    return null;
  }
  if (!isRecord(schema.properties)) return null;
  const names = Object.keys(schema.properties);
  if (names.length < 1 || names.length > MAX_REPLY_FIELDS) return null;
  const required = schema.required === undefined ? [] : schema.required;
  if (!Array.isArray(required) || new Set(required).size !== required.length)
    return null;
  if (
    !required.every((name) => typeof name === "string" && names.includes(name))
  )
    return null;
  const fields: ReplyField[] = [];
  for (const name of names) {
    const property = schema.properties[name];
    if (!FIELD_NAME_PATTERN.test(name) || !isRecord(property)) return null;
    let type: ReplyPrimitive;
    let list = false;
    if (
      hasExactKeys(property, ["type"], ["type"]) &&
      isPrimitive(property.type)
    ) {
      type = property.type;
    } else if (
      hasExactKeys(property, ["type", "items"], ["type", "items"]) &&
      property.type === "array" &&
      isRecord(property.items) &&
      hasExactKeys(property.items, ["type"], ["type"]) &&
      isPrimitive(property.items.type)
    ) {
      type = property.items.type;
      list = true;
    } else {
      return null;
    }
    fields.push({
      ...newReplyField(),
      name,
      type,
      list,
      required: required.includes(name),
    });
  }
  return fields;
}

/** The form state of a saved agent. A missing value is free text; anything unrecognised is kept as is. */
export function replyFormatFromAgent(
  agent: object | null | undefined,
): ReplyFormatState {
  if (
    !agent ||
    !("replyContract" in agent) ||
    agent.replyContract === undefined
  )
    return defaultReplyFormat();
  const value = agent.replyContract;
  if (
    isRecord(value) &&
    value.kind === "text" &&
    hasExactKeys(value, ["kind"], ["kind"])
  ) {
    return {
      mode: "text",
      fields: [],
      baseline: JSON.stringify({ kind: "text" }),
    };
  }
  if (isRecord(value) && value.kind === "json_object") {
    const fields = parseJsonObjectContract(value);
    if (fields)
      return {
        mode: "json_object",
        fields,
        baseline: JSON.stringify(buildContract(fields)),
      };
  }
  return { mode: "unsupported", fields: [], baseline: UNSUPPORTED };
}

export function buildContract(fields: ReplyField[]): ReplyContract {
  const properties: Record<
    string,
    | { type: ReplyPrimitive }
    | { type: "array"; items: { type: ReplyPrimitive } }
  > = {};
  for (const field of fields) {
    properties[field.name] = field.list
      ? { type: "array", items: { type: field.type } }
      : { type: field.type };
  }
  return {
    kind: "json_object",
    schema: {
      type: "object",
      properties,
      required: fields
        .filter((field) => field.required)
        .map((field) => field.name),
    },
  };
}
