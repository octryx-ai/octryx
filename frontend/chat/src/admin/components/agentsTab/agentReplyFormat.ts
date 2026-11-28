// The server stays the authority; these rules only explain mistakes before saving.
// An unchanged format is not sent, so an ordinary free-text agent stays exactly as it is.

import {
  ABSENT,
  FIELD_NAME_PATTERN,
  MAX_REPLY_CONTRACT_BYTES,
  MAX_REPLY_FIELDS,
  fieldTypeLabel,
  type ReplyContract,
  type ReplyField,
  type ReplyFormatState,
  type ReplyPrimitive,
} from "./agentReplyFields";
import { buildContract, replyFormatFromAgent } from "./agentReplyContract";

export type ReplyFieldIssues = {
  rows: Record<string, string>;
  general: string | null;
  firstKey: string | null;
};

export function replyFieldIssues(fields: ReplyField[]): ReplyFieldIssues {
  const rows: Record<string, string> = {};
  let firstKey: string | null = null;
  const seen = new Set<string>();
  for (let index = 0; index < fields.length; index += 1) {
    const field = fields[index];
    let issue: string | null = null;
    if (!field.name) issue = `Field ${index + 1} needs a name.`;
    else if (!FIELD_NAME_PATTERN.test(field.name)) {
      issue = `The field name "${field.name}" must start with a lowercase letter and use only letters, digits and underscores (at most 64 characters).`;
    } else if (seen.has(field.name)) {
      issue = `The field name "${field.name}" is used more than once.`;
    }
    if (field.name) seen.add(field.name);
    if (issue) {
      rows[field.key] = issue;
      firstKey ??= field.key;
    }
  }
  let general: string | null = null;
  if (!fields.length) general = "Add at least one field, or choose Free text.";
  else if (fields.length > MAX_REPLY_FIELDS) {
    general = `Structured data can have at most ${MAX_REPLY_FIELDS} fields.`;
  } else if (
    firstKey === null &&
    new TextEncoder().encode(JSON.stringify(buildContract(fields))).length >
      MAX_REPLY_CONTRACT_BYTES
  ) {
    general = "The output format is too large (at most 16 KiB).";
  }
  return { rows, general, firstKey };
}

export function replyFieldsError(fields: ReplyField[]): string | null {
  const issues = replyFieldIssues(fields);
  if (!fields.length || fields.length > MAX_REPLY_FIELDS) return issues.general;
  return issues.firstKey ? issues.rows[issues.firstKey] : issues.general;
}

export const REPLY_FORMAT_ERROR_PREFIX = "Output format: ";

export function formErrorAfterReplyFormatChange(
  current: string | null | undefined,
  next: ReplyFormatState,
): string | null {
  if (
    typeof current !== "string" ||
    !current.startsWith(REPLY_FORMAT_ERROR_PREFIX)
  ) {
    return current ?? null;
  }
  const check = replyFormatForSave(next);
  return check.ok ? null : check.error;
}

export type ReplyFormatSave =
  | { ok: true; send: false }
  | { ok: true; send: true; value: ReplyContract }
  | { ok: false; error: string };

export function replyFormatForSave(state: ReplyFormatState): ReplyFormatSave {
  // Nothing is sent for an unrecognised saved value, so the server decides (and refuses with 422).
  if (state?.mode === "text") {
    return state.baseline === ABSENT ||
      state.baseline === JSON.stringify({ kind: "text" })
      ? { ok: true, send: false }
      : { ok: true, send: true, value: { kind: "text" } };
  }
  if (state?.mode !== "json_object") return { ok: true, send: false };
  const error = replyFieldsError(state.fields);
  if (error)
    return { ok: false, error: `${REPLY_FORMAT_ERROR_PREFIX}${error}` };
  const value = buildContract(state.fields);
  return JSON.stringify(value) === state.baseline
    ? { ok: true, send: false }
    : { ok: true, send: true, value };
}

/** While the saved format is unrecognised the server refuses every save (422), so the way out is named. */
export function replyFormatSaveError(
  state: ReplyFormatState | undefined,
  message: string,
): string {
  return state?.mode === "unsupported"
    ? `The server refused the save because this agent's saved output format is not valid: ${message} Choose Free text, or define the fields again as Structured data, then save.`
    : message;
}

const EXAMPLE_VALUES: Record<ReplyPrimitive, unknown> = {
  string: "text",
  integer: 1,
  number: 0.5,
  boolean: true,
};

export function replyFormatPreview(fields: ReplyField[]): string {
  const example: Record<string, unknown> = {};
  for (const field of fields) {
    if (!field.name) continue;
    example[field.name] = field.list
      ? [EXAMPLE_VALUES[field.type]]
      : EXAMPLE_VALUES[field.type];
  }
  return JSON.stringify(example, null, 2);
}

export function replyFormatSummary(agent: object | null | undefined): {
  label: string;
  fields: { name: string; type: string; required: boolean }[];
} {
  const state = replyFormatFromAgent(agent);
  if (state.mode === "json_object") {
    return {
      label: "Structured data (JSON, checked)",
      fields: state.fields.map((field) => ({
        name: field.name,
        type: fieldTypeLabel(field),
        required: field.required,
      })),
    };
  }
  if (state.mode === "unsupported") {
    return {
      label:
        "The saved output format is not valid. The agent cannot be saved until a valid format is chosen: edit it and choose Free text, or define the fields again.",
      fields: [],
    };
  }
  return { label: "Free text (not checked)", fields: [] };
}
