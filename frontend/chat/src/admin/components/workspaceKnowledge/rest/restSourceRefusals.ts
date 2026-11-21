// Custom REST source: every refused save, dry run or run reason in words, at the field it belongs to.
import { MAPPING_FIELDS } from "./restSourceForm";
import { WORKSPACE_ADMIN_ONLY } from "./restSourceRules";

// ---- refusals -----------------------------------------------------------------------------------------------------

export type Refusal = { field: string; text: string };

// The fixed codes of (422 with a field, 409 refused, 403 admin-only) in words, at the field they belong to.
const CODE_WORDS: Record<string, Refusal> = {
  // The API's connection is not released to this Workspace (also for a platform admin: release it first).
  source_connection_not_granted: { field: "scope.definition", text: "This connection is not released to this Workspace. A platform admin releases it in Admin › Connections: open the connection and tick this Workspace under Workspaces." },
  rest_source_visibility_admin_only: { field: "scope.visibility", text: WORKSPACE_ADMIN_ONLY },
  custom_rest_definition_unavailable: { field: "scope.definition", text: "This REST API is not active. Activate it in Connections › REST APIs." },
  custom_rest_no_connection: { field: "scope.definition", text: "This REST API has no connection for this Workspace. Add one in Connections › REST APIs." },
  custom_rest_operation_unavailable: { field: "scope.operation", text: "This operation is not enabled on the API. Pick another one." },
  custom_rest_operation_not_a_read: { field: "scope.operation", text: "A source reads with a read operation. Pick a read operation." },
  custom_rest_role_required: { field: "scope.role", text: "This operation's grants have a scope, so pick the role to read as. The scope is enforced as that role." },
  custom_rest_role_not_granted: { field: "scope.role", text: "This role has no grant on the operation in this Workspace. Pick a granted role." },
  custom_rest_detail_param_required: { field: "scope.detail_param", text: "Pick the argument of the detail operation that takes the record's id." },
  custom_rest_detail_operation_required: { field: "scope.detail_operation", text: "Pick the read operation that returns one record." },
  custom_rest_since_param_unknown: { field: "scope.updated_since_param", text: "The list operation has no such argument. Pick one it declares, or leave it empty." },
  custom_rest_version_required: { field: "mapping.updated_at", text: "Map Updated or Version: a sync re-reads only records that changed." },
  custom_rest_invalid_arguments: { field: "scope.arguments", text: "Arguments are names with short single-line values (at most 20)." },
  custom_rest_too_large: { field: "", text: "The configuration is too large. Remove arguments or shorten the paths." },
  custom_rest_unknown_field: { field: "", text: "The server does not know one of the settings. Reload the page and try again." },
  custom_rest_object_required: { field: "", text: "The server did not accept the configuration's shape. Reload the page and try again." },
};

// A field-attributed 422 whose code needs the field's own words.
const FIELD_WORDS: Record<string, string> = {
  "scope.definition": "Pick a REST API from the list.",
  "scope.operation": "Pick an operation from the list.",
  "scope.role": "Pick a role from the list.",
  "scope.detail_operation": "Pick an operation from the list.",
  "scope.detail_param": "Pick an argument from the list.",
  "scope.updated_since_param": "Use the argument's name: letters, digits and _ $ @ . : -.",
  "scope.media_type": "Pick one of the offered content types.",
  "scope.visibility": "Pick restricted or workspace.",
  "mapping.content": "Name the field that holds the text.",
};

// Run and sample reasons of a REST source (sync/rest_source.py), in words for the status and the dry run.
const REASON_WORDS: Record<string, string> = {
  custom_rest_detail_out_of_scope: "the role's result filter refused the record's detail",
  custom_rest_cursor_too_long: "the API's next-page address is too long to store",
  custom_rest_not_granted: "the role has no grant on the operation",
  custom_rest_scope_violation: "the call would leave the role's data scope",
  custom_rest_egress_refused: "the API's address is refused by the egress policy",
};

/** A run or sample reason in words; codes with a refusal sentence use it. */
export function restReasonText(reason: string): string {
  if (!reason) return "";
  if (REASON_WORDS[reason]) return REASON_WORDS[reason];
  const words = CODE_WORDS[reason]?.text;
  if (words) return words.replace(/\.$/, "").replace(/^./, (first) => first.toLowerCase());
  return reason.replace(/^custom_rest_/, "").replace(/_/g, " ");
}

/** Every refused save or dry run in words, at its field ("" when it belongs to none). */
export function restRefusalOf(error: unknown): Refusal {
  const failure = (error && typeof error === "object" ? error : {}) as { status?: number; reason?: string | null; field?: string | null; message?: string };
  const code = failure.reason ?? "";
  const field = failure.field ?? "";
  // Name the connection when the server does (its own sentence comes with the error).
  if (code === "source_connection_not_granted" && failure.message) return { field: CODE_WORDS[code].field, text: failure.message };
  if (CODE_WORDS[code]) return { field: CODE_WORDS[code].field || field, text: CODE_WORDS[code].text };
  if (code === "custom_rest_invalid_path" || code === "custom_rest_field_required") {
    const name = field.startsWith("mapping.") ? field.slice(8) : "";
    const label = MAPPING_FIELDS.find((entry) => entry.name === name)?.label.replace(" *", "") ?? (name === "content" ? "Content field" : "This field");
    return { field, text: code === "custom_rest_invalid_path" ? `${label}: use a dot path, like fields.summary.` : `${label} is required.` };
  }
  if (field && FIELD_WORDS[field]) return { field, text: FIELD_WORDS[field] };
  const status = failure.status ?? 0;
  if (status === 401) return { field: "", text: "Your session ended. Sign in again." };
  if (status === 403) return { field: "", text: "Only a Workspace admin or owner can set up sources." };
  if (status === 404) return { field: "", text: "This source no longer exists. Close the form and reload." };
  if (code.startsWith("custom_rest_")) return { field, text: `The API refused the call (${restReasonText(code)}). Check its connection and grants in Connections › REST APIs.` };
  if (code) return { field, text: `The server refused this (${code.replace(/_/g, " ")}).` };
  if (status >= 500) return { field: "", text: "The server did not answer as expected. Try again." };
  if (status >= 400) return { field, text: "The server did not accept this. Check the settings." };
  return { field: "", text: failure.message || "The request failed. Check your connection and try again." };
}
