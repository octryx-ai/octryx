// Custom REST Work source: refused requests in words, and the setup step a refused field is edited on.

import { SYNC_MODE_REFUSAL } from "./intakeSyncModel";
import { FIELD_LABELS } from "./restIntakeForm";

export type Refusal = { field: string; text: string };

const CODE_WORDS: Record<string, Refusal> = {
  custom_rest_role_required: { field: "what.role",
    text: "This operation's grants have a scope, so pick the role to read as. The scope is enforced as that role." },
  custom_rest_role_not_granted: { field: "what.role", text: "This role has no grant on the list operation in this Workspace. Pick a granted role." },
  custom_rest_operation_unavailable: { field: "what.operation", text: "This operation is not enabled on the API. Pick another list operation." },
  custom_rest_operation_not_a_read: { field: "what.operation", text: "A source lists items with a read operation. Pick a read operation." },
  custom_rest_no_connection: { field: "connection_id", text: "This API has no active connection for this Workspace. Add one in Connections › REST APIs." },
  custom_rest_definition_unavailable: { field: "connection_id", text: "This REST API is not active. Activate it in Connections › REST APIs." },
  intake_connection_not_found: { field: "connection_id", text: "Pick a REST API this Workspace has a connection for." },
  custom_rest_write_back_operation_invalid: { field: "how.write_back.operation", text: "Pick an enabled write operation of the same API." },
  intake_sample_unsupported: { field: "", text: "This source has no dry run. Use the preview instead." },
};

const FIELD_WORDS: Record<string, string> = {
  "what.operation": "Pick the list operation.",
  "what.role": "Pick one of the granted roles.",
  "what.arguments": "Arguments are names with values.",
  "how.field_mapping": "Map key, title and status: an item needs a stable key, a title and a status.",
  "how.status_mapping": "Each status maps to one Octryx state.",
  "how.closed_statuses": "Closed statuses are status names of at most 120 characters.",
  "how.write_back": "Pick the write operation of the same API.",
  "how.write_back.body": "The body is a JSON object.",
  "how.sync_mode": SYNC_MODE_REFUSAL,
  schedule: "Pick a schedule or enter a valid cron expression.",
};

/** A refused request in words, and the field it belongs to ("" when it belongs to none). Every 4xx gets words. */
export function refusalOf(error: unknown): Refusal {
  const failure = (error && typeof error === "object" ? error : {}) as { status?: number; code?: string | null; message?: string; detail?: Record<string, unknown> };
  const code = failure.code ?? "";
  if (CODE_WORDS[code]) return CODE_WORDS[code];
  const field = typeof failure.detail?.field === "string" ? failure.detail.field : "";
  if (field.startsWith("how.field_mapping.")) {
    const name = field.slice("how.field_mapping.".length);
    return { field, text: `${FIELD_LABELS[name] ?? name}: use a dot path, like fields.summary.` };
  }
  if (FIELD_WORDS[field]) return { field, text: FIELD_WORDS[field] };
  const status = failure.status ?? 0;
  // A refusal at a field this page has no words for: the server's sentence without the field's technical name.
  const message = typeof failure.message === "string" ? failure.message.trim() : "";
  if (field && status >= 400 && status < 500 && message) {
    const sentence = message.startsWith(`${field} `) ? message.slice(field.length + 1) : message;
    return { field, text: sentence.charAt(0).toUpperCase() + sentence.slice(1) };
  }
  if (status === 401) return { field: "", text: "Your session ended. Sign in again." };
  if (status === 403) return { field: "", text: "Only a Workspace admin or owner can set up Work sources." };
  if (status === 404) return { field: "", text: "This intake no longer exists. Close the drawer and reload." };
  if (status === 409 && code.startsWith("custom_rest_")) {
    return { field: "", text: `The API refused the call (${code.slice("custom_rest_".length).replace(/_/g, " ")}). Check its connection and grants.` };
  }
  if (status >= 500) return { field: "", text: "The API did not answer as expected. Try again, or test the operation in Connections › REST APIs." };
  if (status >= 400) return { field, text: "The server did not accept this. Check the highlighted settings." };
  return { field: "", text: "The request failed. Check your connection and try again." };
}

/** The setup step a refused field is edited on: What = 1, When = 2, How = 3; the source = 0. */
export function stepOfField(field: string): number | null {
  if (!field) return null;
  if (field === "connection_id") return 0;
  if (field.startsWith("what.")) return 1;
  if (field === "schedule") return 2;
  if (field.startsWith("how.")) return 3;
  return null;
}
