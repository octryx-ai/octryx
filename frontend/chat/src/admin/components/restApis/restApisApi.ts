import { readJson } from "../../utils/adminPanelHelpers";

// Custom REST APIs: the backend's admin routes for reads and writes (web/routers/panel_rest_connectors.py), all
// platform-admin only. Field names follow the backend. readJson throws an Error carrying `status` and the server's
// `detail` text as message; restApisModel.restErrorView turns it into words at the field.

export type AuthScheme = "none" | "api_key_header" | "api_key_query" | "bearer" | "basic" | "oauth2_client_credentials";

export type RestAuth = {
  scheme: AuthScheme;
  header_name?: string;
  query_name?: string;
  token_url?: string;
  scopes?: string[];
  // Set by an import: the security scheme's name in the document.
  source_scheme?: string;
  // Backend: fetch a CSRF token before each write (SAP Gateway); absent = off.
  csrf?: RestCsrf;
};

export type RestCsrf = { fetch: true; header: string; fetch_path?: string };

export type RestParameter = {
  name: string;
  in: "path" | "query" | "header";
  required: boolean;
  description: string;
  schema: { type?: string; enum?: unknown[]; [key: string]: unknown };
  // Backend: `name` is what the model sees (`select`); `wire_name` the name sent (`$select`), only when it differs.
  wire_name?: string;
  explode?: boolean;
};

export type ParamOverlay = { description?: string; hidden?: boolean; value?: string | number | boolean };

export type ResultFilter = { field: string; value: string | number | boolean };

export type RestGrant = {
  role: string;
  workspace_id: string | null;
  scope: Record<string, string | number | boolean>;
  result_filter: ResultFilter | null;
  // Backend: dotted body paths and the value each must hold (set last in a JSON body; only with a request body).
  body_scope?: Record<string, string | number | boolean>;
};

/** The run class a write needs (backend); null for a read. */
export type WriteCapability = "deliver" | "change";

export type PaginationType = "none" | "cursor" | "offset" | "next_url" | "link_header";

export type RestPagination = {
  type: PaginationType;
  cursor_path?: string;
  cursor_param?: string;
  offset_param?: string;
  limit_param?: string;
  page_size?: number;
  next_path?: string;
};

export type RestOperation = {
  id: string;
  op_key: string;
  tool_name: string;
  method: string;
  path: string;
  summary: string;
  parameters: RestParameter[];
  request_body: unknown;
  enabled: boolean;
  read_only: boolean;
  is_read: boolean;
  llm_name: string;
  llm_description: string;
  params_overlay: Record<string, ParamOverlay>;
  grants: RestGrant[];
  response_select: string[];
  records_path: string;
  pagination: RestPagination;
  // Backend: the effective run class of a write (null for a read), what the admin set ("" = default), whether a
  // PUT/DELETE may be retried, and the scope-bypass warnings of this operation.
  capability?: WriteCapability | null;
  declared_capability?: WriteCapability | "";
  idempotent?: boolean;
  scope_warnings?: string[];
  // Backend: the OData template the stored records path and pagination equal ("" = set by hand), and why the
  // operation cannot be enabled ("odata_batch"; "" = it can).
  preset?: OdataTemplate | "";
  // Backend: where the effective preset comes from: the operation's own settings, the API's default (a
  // collection read without own settings) or none (a single-entity read, or no default).
  preset_source: PresetSource;
  unsupported?: string;
  // Only on the answer of an operation PUT.
  warnings?: string[];
};

export type OdataTemplate = "odata_v2" | "odata_v2_offset" | "odata_v4";
export type PresetSource = "operation" | "definition" | "none";

export type RestDefinition = {
  id: string;
  key: string;
  name: string;
  description: string;
  source_kind: "manual" | "openapi" | string;
  source_url: string;
  spec_version: string;
  servers: string[];
  auth: RestAuth;
  timeout_seconds: number;
  // Backend: the OData template every collection read without own settings uses ("" = none).
  default_preset?: OdataTemplate | "";
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
  // Only on read, import and update (not in the list). `warnings` includes the per-operation ones ("'<op>': …").
  operations?: RestOperation[];
  warnings?: string[];
};

/** One entry of the list (backend): the counts are the server's, warnings is a count. */
export type RestDefinitionListEntry = Omit<RestDefinition, "operations" | "warnings"> & {
  operations: number;
  enabled_operations: number;
  connections: number;
  warnings: number;
};

export type SecretField = "api_key" | "token" | "password" | "client_secret";
export type PublicField = "username" | "client_id" | "token_url" | "scope" | "audience";

export type RestConnection = {
  id: string;
  definition_id: string;
  project_id: string | null;
  owner: "workspace" | "platform";
  name: string;
  base_url: string;
  is_active: boolean;
  fields: Partial<Record<PublicField, string>>;
  secret_status: Record<SecretField, boolean>;
  missing_for_auth: string[];
};

export type RunPayload = {
  id: string;
  status: "succeeded" | "refused" | "failed" | "running" | string;
  failure_category: string | null;
  http_status: number | null;
  dropped_out_of_scope: number;
  duration_ms?: number | null;
};

export type TestSuccess = {
  api: string;
  operation: string;
  status_code: number;
  data: unknown;
  record_count: number;
  dropped_out_of_scope: number;
  next_cursor: string | null;
  scope: { params: Record<string, unknown>; result_filter: ResultFilter | null };
  retries: number;
  run: RunPayload;
};

export type TestRefusal = { error: string; code?: string; run?: RunPayload };

export type TestAnswer = TestSuccess | TestRefusal;

export type RestCall = {
  id: string;
  tool_name: string;
  identity: string;
  status: string;
  failure_category: string;
  http_status: number | null;
  scope: AppliedCallScope | RefusedCallScope;
  records: number;
  dropped_out_of_scope: number;
  duration_ms: number | null;
  user_id: string | null;
  workspace_id: string | null;
  connection_id: string | null;
  started_at: string | null;
  // Backend: the redacted error text, and the names (null when there is none).
  error: string;
  user_name: string | null;
  workspace_name: string | null;
  // Backend: what admitted a write (the central approval or the chat's write plan), and the chat it ran in.
  approval_id?: string | null;
  write_plan_id?: string | null;
  session_id?: string | null;
  // Whether the operation writes (null when it was removed since).
  write?: boolean | null;
  // Backend: the API and operation the call belongs to.
  definition_id?: string | null;
  operation_id?: string | null;
};

export type AppliedCallScope = {
  refused?: false;
  role?: string;
  params?: Record<string, unknown>;
  result_filter?: ResultFilter | null;
  // Backend: body fields the grant set.
  body?: Record<string, unknown>;
};
/** A scope refusal's audit: the scoped parameters the call asked for, and every scope the caller's grants allow. */
export type RefusedCallScope = {
  refused: true;
  requested: Record<string, unknown>;
  allowed: Array<{ role: string; params: Record<string, unknown>; result_filter: ResultFilter | null }>;
};

const BASE = "/admin/chat/api/panel/rest-apis";
const enc = encodeURIComponent;
const send = <T>(path: string, method: string, body?: unknown) =>
  readJson<T>(`${BASE}${path}`, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export const listDefinitions = () => readJson<RestDefinitionListEntry[]>(BASE);
export const loadDefinition = (id: string) => readJson<RestDefinition>(`${BASE}/${enc(id)}`);
export const createDefinition = (body: unknown) => send<RestDefinition>("", "POST", body);
export const importDefinition = (body: unknown) => send<RestDefinition>("/import", "POST", body);
export const updateDefinition = (id: string, body: unknown) => sendKeepingLoc<RestDefinition>(`/${enc(id)}`, "PUT", body);
export const deleteDefinition = (id: string) =>
  send<{ status: string; recorded_calls_kept: number }>(`/${enc(id)}`, "DELETE");

export const addOperation = (id: string, body: unknown) => send<RestOperation>(`/${enc(id)}/operations`, "POST", body);
export const updateOperation = (id: string, opId: string, body: unknown) =>
  send<RestOperation>(`/${enc(id)}/operations/${enc(opId)}`, "PUT", body);
export const deleteOperation = (id: string, opId: string) =>
  send<{ status: string }>(`/${enc(id)}/operations/${enc(opId)}`, "DELETE");
export const testOperation = (id: string, opId: string, body: unknown) =>
  send<TestAnswer>(`/${enc(id)}/operations/${enc(opId)}/test`, "POST", body);

export const listConnections = (id: string) => readJson<RestConnection[]>(`${BASE}/${enc(id)}/connections`);
export const createConnection = (id: string, body: unknown) =>
  send<RestConnection>(`/${enc(id)}/connections`, "POST", body);
export const updateConnection = (id: string, connectionId: string, body: unknown) =>
  send<RestConnection>(`/${enc(id)}/connections/${enc(connectionId)}`, "PUT", body);
export const deleteConnection = (id: string, connectionId: string) =>
  send<{ status: string }>(`/${enc(id)}/connections/${enc(connectionId)}`, "DELETE");

/** The latest calls; `query` from restApisModel.callsQuery (limit, definition_id, op_id). */
export const listCalls = (query: string) => readJson<RestCall[]>(`/admin/chat/api/panel/rest-api-calls?${query}`);

// The definition PUT answers an invalid server with 422 and a validation list (backend:
// `detail[0].loc == ["body","servers",<index>]`). readJson keeps only a text or object detail, so this keeps the
// first entry's `loc` and `msg` on the error; restApisModel.restErrorView marks that server row.
async function sendKeepingLoc<T>(path: string, method: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method, credentials: "same-origin", body: JSON.stringify(body),
    headers: { Accept: "application/json", "Content-Type": "application/json" },
  });
  if (response.ok) return (await response.json()) as T;
  const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  const detail = payload?.detail;
  const first = Array.isArray(detail) && detail[0] && typeof detail[0] === "object" ? detail[0] as { loc?: unknown; msg?: unknown } : null;
  const message = typeof detail === "string" ? detail
    : first && typeof first.msg === "string" ? first.msg
      : detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string"
        ? (detail as { message: string }).message : response.statusText || "Request failed";
  // A typed refusal names its field (backend: `{field: "default_preset", message}`).
  const field = detail && typeof detail === "object" && !Array.isArray(detail) && typeof (detail as { field?: unknown }).field === "string"
    ? (detail as { field: string }).field : undefined;
  throw Object.assign(new Error(message), { status: response.status, loc: Array.isArray(first?.loc) ? first.loc : undefined, field });
}

// Roles a grant can name: platform roles and work-role keys. Either list may be refused or missing; the editor
// then offers free text only.
export async function loadRoleOptions(): Promise<{ platform: string[]; work: Array<{ key: string; name: string }> }> {
  const [platform, work] = await Promise.all([
    readJson<Array<{ name: string }>>("/admin/chat/api/panel/roles").catch(() => []),
    readJson<{ roles?: Array<{ key: string; name: string }> }>("/api/v1/work-roles/roles").catch(() => ({ roles: [] })),
  ]);
  return {
    platform: (Array.isArray(platform) ? platform : []).map((role) => role.name).filter(Boolean),
    work: (work.roles ?? []).filter((role) => role.key).map((role) => ({ key: role.key, name: role.name })),
  };
}
