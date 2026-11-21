// REST API model: refusals of the admin API in words, with the field they belong to.
import { TEST_WRITE_NOTE } from "./restOperationsModel";

// ---- refusals at the field ---------------------------------------------------------------------------------------

// `index`: for "servers", the position in the body's list (serverRowOfIndex finds the row it came from).
export type RestErrorView = { field: string | null; text: string; index?: number };

const FIELD_RULES: ReadonlyArray<[RegExp, string, string | null]> = [
  [/^A REST API with the key/, "key", "Another REST API already uses this key."],
  [/^key:/, "key", "Use 1–24 lower-case letters, digits or _, starting with a letter."],
  [/^auth\.header_name/, "header_name", "The key header may not be Host or Cookie."],
  [/^auth\.csrf\.header/, "csrf_header", "The token header must be its own header, not Authorization, Cookie or Host."],
  [/^auth\.csrf\.fetch_path/, "csrf_fetch_path", "Give a path on the API's host, starting with /, or leave it empty."],
  [/OData \$batch operation/, "enabled", "$batch is not supported. Enable the single operations instead."],
  [/^preset must be/, "template", "Choose one of the offered templates."],
  [/^auth\./, "scheme", null],
  [/^timeout_seconds/, "timeout", "Give a whole number of seconds between 1 and 300."],
  [/^Fetching the OpenAPI document answered HTTP (\d+)/, "spec_url", null],
  [/^base_url/, "base_url", "Give an http(s) address with a host, without user, password, query or fragment."],
  [/already has a connection in that scope/, "workspace", "This API already has a connection there. Edit that one instead."],
  [/^Workspace not found/, "workspace", "This Workspace no longer exists."],
  [/^Another operation of this API is already named/, "llm_name", "Another operation of this API already has this name."],
  [/^llm_name:/, "llm_name", "Use 1–32 lower-case letters, digits or _, starting with a letter."],
  [/^params_overlay/, "overlay", null],
  [/^grant body_scope needs an operation with a request body/, "grants", "A body scope needs an operation with a request body."],
  [/^grant body_scope: not a dotted field path/, "grants", "A body field is a dotted path, e.g. assignment_group or group.id."],
  [/^grant body_scope value of .* must be/, "grants", "Each body field needs a single value (text, number or true/false)."],
  [/^grant body_scope must be/, "grants", "The body scope must be a list of fields and values."],
  [/^grant |^grants |^each grant|^result_filter/, "grants", null],
  [/^capability must be/, "capability", "Choose Deliver or Change."],
  [/^idempotent can be set/, "idempotent", "Only a PUT or DELETE can be marked safe to repeat."],
  [/^A write operation is not test-called/, "test", TEST_WRITE_NOTE],
  [/^response_select/, "response_select", null],
  [/^records_path/, "records_path", "Use a dotted path, e.g. result.items."],
  [/^pagination/, "pagination", null],
  [/^The operation key '.*' exists/, "op_key", "This API already has an operation with this key."],
  [/^op_key:/, "op_key", "Use 1–32 lower-case letters, digits or _, starting with a letter."],
  [/^method must/, "method", null],
  [/^path must/, "path", "Start the path with /; never a full URL."],
  [/^each parameter|^parameter 'in'/, "parameters", null],
];

/** Words for a server the definition PUT refused (backend: "servers[1] has no host: '…'"). */
function serverProblemText(message: string): string {
  if (/has no host/.test(message)) return "This address has no host.";
  if (/must start with http/.test(message)) return "Start the address with https:// or http://.";
  return "This is not a valid address.";
}

export const fieldError = (error: RestErrorView | null, field: string) => (error?.field === field ? error.text : null);

/** A refusal of the admin API in words, with the field it belongs to (null: a line for the whole form). */
export function restErrorView(error: unknown, context: "import" | "other" = "other"): RestErrorView {
  const status = typeof (error as { status?: unknown })?.status === "number" ? (error as { status: number }).status : 0;
  const message = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  if (status === 401 || status === 403) return { field: null, text: "Only platform admins manage REST APIs." };
  if ((error as { field?: unknown })?.field === "default_preset") {
    return { field: "default_preset", text: "Choose one of the offered templates, or no template." };
  }
  const loc = (error as { loc?: unknown })?.loc;
  if (Array.isArray(loc) && loc[1] === "servers") {
    return typeof loc[2] === "number"
      ? { field: "servers", index: loc[2], text: serverProblemText(message) }
      : { field: "servers", text: "Give one address per line." };
  }
  if (/not found$/.test(message) && !/^Workspace/.test(message)) {
    return { field: null, text: "This item no longer exists. Reload the list." };
  }
  for (const [pattern, field, words] of FIELD_RULES) {
    const match = message.match(pattern);
    if (!match) continue;
    if (field === "spec_url") return { field, text: `The address answered HTTP ${match[1]}; check the URL.` };
    return { field, text: words ?? message };
  }
  if (status === 400 && context === "import") return { field: "spec", text: `The document could not be read: ${message}` };
  if (status === 422) return { field: null, text: "The form was incomplete; check the fields and save again." };
  return { field: null, text: message || "The request failed." };
}
