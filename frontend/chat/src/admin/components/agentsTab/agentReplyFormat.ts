// The agent's checked output format (shared contract). Pure: no requests, no React.
//
// Contract: the panel agent payload carries `replyContract`; create/update accept `reply_contract`. A
// value is {kind: "text"} or {kind: "json_object", schema: {type: "object", properties, required}}.
// Each property is {type: string|integer|number|boolean} or {type: "array", items: {type: <one of
// those>}}; 1–32 distinct field names matching the server's field name rule; `required` names only
// declared fields, once each; at most 16 KiB serialized. A missing value means free text.
//
// - The server stays the authority; this mirrors its rules only to explain mistakes before saving.
// - An unchanged format is not sent (an omitted update keeps the stored value), so an ordinary
//   free-text agent stays exactly as it is. Choosing Free text for a checked agent sends {kind: "text"}.
// - A saved value this form cannot represent is never replaced silently: nothing is sent for it until
//   the author explicitly chooses a format. Such a value is invalid on the server too (same rules),
//   and the server refuses every save of the agent until a valid format is chosen (
//   reply_contract_column_for_write, HTTP 422), so the form says so and offers the two choices.

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

/** Problems per field row (keyed by row key) and for the list as a whole, in the author's words. */
export type ReplyFieldIssues = {
  rows: Record<string, string>;
  general: string | null;
  /** The first row with a problem, in display order. */
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

/** The first problem with the structured fields, in the author's words; null when they are valid. */
export function replyFieldsError(fields: ReplyField[]): string | null {
  const issues = replyFieldIssues(fields);
  if (!fields.length || fields.length > MAX_REPLY_FIELDS) return issues.general;
  return issues.firstKey ? issues.rows[issues.firstKey] : issues.general;
}

/** Prefix of a save refused by the output format, so the form can update or clear that message. */
export const REPLY_FORMAT_ERROR_PREFIX = "Output format: ";

/**
 * The form error after the output format changed. A save message about the output format
 * follows the fields (updated, or cleared once valid); any other message is left as it is.
 */
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

/** What a save sends: nothing when unchanged or unrecognised, {kind: "text"} or the checked format. */
export function replyFormatForSave(state: ReplyFormatState): ReplyFormatSave {
  // Only an explicit text or structured choice is ever sent; nothing (never null, never text) is sent
  // for an unrecognised saved value or any other state, so the server decides (and refuses, 422).
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

/**
 * The form error for a refused save. While the saved format is unrecognised, the server refuses every
 * save of the agent (422); its message is kept verbatim and the way out is named.
 */
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

/** A short example of a reply that matches the fields (names as typed). */
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

/** The agent detail line for the saved format. */
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
