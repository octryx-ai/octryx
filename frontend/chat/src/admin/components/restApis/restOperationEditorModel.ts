import type { PaginationType, ParamOverlay, RestGrant, RestOperation, WriteCapability } from "./restApisApi";
import { idempotentAllowed, OFFERED_TO_NOBODY, scopeWithoutFilterText } from "./restOperationsModel";
import { answerBody, initialPresetChoice, type PresetChoice } from "./restOdataModel";

export type ScopeRow = { param: string; value: string };
export type GrantDraft = {
  role: string;
  workspaceId: string;
  scope: ScopeRow[];
  bodyScope: ScopeRow[];
  filterField: string;
  filterValue: string;
};
export type OverlayDraft = Record<string, { description: string; hidden: boolean; value: string }>;
export type PaginationDraft = {
  type: PaginationType;
  cursor_path: string;
  cursor_param: string;
  offset_param: string;
  limit_param: string;
  page_size: string;
  next_path: string;
};
export type OperationDraft = {
  enabled: boolean;
  llmName: string;
  llmDescription: string;
  readOnly: boolean;
  overlay: OverlayDraft;
  grants: GrantDraft[];
  responseSelect: string;
  recordsPath: string;
  pagination: PaginationDraft;
  capability: WriteCapability;
  idempotent: boolean;
  // "" means set by hand: the records path and pages above are sent as they are.
  presetChoice: PresetChoice;
};

export const PAGINATION_TYPES: ReadonlyArray<{ value: PaginationType; label: string }> = [
  { value: "none", label: "One page" },
  { value: "cursor", label: "Cursor in the answer" },
  { value: "offset", label: "Offset and limit" },
  { value: "next_url", label: "Next-page URL in the answer" },
  { value: "link_header", label: "Link header (rel=next)" },
];

const text = (value: unknown) => (value === undefined || value === null ? "" : String(value));

export function grantDraft(grant?: RestGrant): GrantDraft {
  return {
    role: grant?.role ?? "",
    workspaceId: grant?.workspace_id ?? "",
    scope: Object.entries(grant?.scope ?? {}).map(([param, value]) => ({ param, value: text(value) })),
    bodyScope: Object.entries(grant?.body_scope ?? {}).map(([param, value]) => ({ param, value: text(value) })),
    filterField: grant?.result_filter?.field ?? "",
    filterValue: text(grant?.result_filter?.value),
  };
}

export function operationDraft(op: RestOperation): OperationDraft {
  const overlay: OverlayDraft = {};
  for (const param of op.parameters) {
    const entry: ParamOverlay = op.params_overlay[param.name] ?? {};
    overlay[param.name] = { description: entry.description ?? "", hidden: Boolean(entry.hidden), value: text(entry.value) };
  }
  const p = op.pagination ?? { type: "none" };
  const draft: OperationDraft = {
    enabled: op.enabled,
    llmName: op.llm_name,
    llmDescription: op.llm_description,
    readOnly: op.read_only,
    overlay,
    grants: op.grants.map(grantDraft),
    responseSelect: op.response_select.join("\n"),
    recordsPath: op.records_path,
    pagination: {
      type: p.type, cursor_path: text(p.cursor_path), cursor_param: text(p.cursor_param), offset_param: text(p.offset_param),
      limit_param: text(p.limit_param), page_size: text(p.page_size), next_path: text(p.next_path),
    },
    capability: op.declared_capability === "change" ? "change" : "deliver",
    idempotent: Boolean(op.idempotent),
    presetChoice: "",
  };
  return { ...draft, presetChoice: initialPresetChoice(op, draft) };
}

/** The schema type decides, because the executor compares values exactly. */
export function coerceValue(raw: string, type?: string): string | number | boolean {
  const value = raw.trim();
  if ((type === "integer" || type === "number") && value !== "" && Number.isFinite(Number(value))) return Number(value);
  if (type === "boolean" && (value === "true" || value === "false")) return value === "true";
  return value;
}

export const paramType = (op: Pick<RestOperation, "parameters">, name: string) =>
  op.parameters.find((param) => param.name === name)?.schema?.type;

type JsonSchema = { type?: unknown; properties?: Record<string, JsonSchema> };
const asSchema = (value: unknown): JsonSchema | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as JsonSchema) : null;

function bodySchema(op: Pick<RestOperation, "request_body">): JsonSchema | null {
  const body = asSchema(op.request_body);
  if (!body) return null;
  return asSchema((body as { schema?: unknown }).schema) ?? body;
}

/** The server refuses a body scope without a request body. */
export const hasRequestBody = (op: Pick<RestOperation, "request_body">) => asSchema(op.request_body) !== null;

export function bodyFieldPaths(op: Pick<RestOperation, "request_body">): Array<{ path: string; type: string }> {
  const out: Array<{ path: string; type: string }> = [];
  const walk = (schema: JsonSchema | null, prefix: string, depth: number) => {
    for (const [name, child] of Object.entries(schema?.properties ?? {})) {
      const path = prefix ? `${prefix}.${name}` : name;
      if (child?.properties && depth < 3) walk(child, path, depth + 1);
      else if (typeof child?.type === "string" && ["string", "integer", "number", "boolean"].includes(child.type)) out.push({ path, type: child.type });
    }
  };
  walk(bodySchema(op), "", 0);
  return out;
}

const bodyFieldType = (op: Pick<RestOperation, "request_body">, path: string) =>
  bodyFieldPaths(op).find((field) => field.path === path)?.type;

function grantBody(op: RestOperation, grant: GrantDraft): RestGrant {
  const scope: RestGrant["scope"] = {};
  for (const row of grant.scope) {
    if (row.param && row.value.trim() !== "") scope[row.param] = coerceValue(row.value, paramType(op, row.param));
  }
  const bodyScope: NonNullable<RestGrant["body_scope"]> = {};
  for (const row of grant.bodyScope) {
    const path = row.param.trim();
    if (path && row.value.trim() !== "") bodyScope[path] = coerceValue(row.value, bodyFieldType(op, path));
  }
  const field = grant.filterField.trim();
  return {
    role: grant.role.trim(),
    workspace_id: grant.workspaceId || null,
    scope,
    result_filter: field ? { field, value: coerceValue(grant.filterValue, undefined) } : null,
    ...(Object.keys(bodyScope).length ? { body_scope: bodyScope } : {}),
  };
}

export function paginationBody(draft: PaginationDraft): Record<string, unknown> {
  const body: Record<string, unknown> = { type: draft.type };
  const keep = (name: keyof PaginationDraft) => { if (draft[name].trim()) body[name] = draft[name].trim(); };
  if (draft.type === "cursor") { keep("cursor_path"); keep("cursor_param"); }
  if (draft.type === "offset") {
    keep("offset_param"); keep("limit_param");
    if (draft.page_size.trim()) body.page_size = Number(draft.page_size);
  }
  if (draft.type === "next_url") keep("next_path");
  return body;
}

/** The server refuses read_only off a POST, the run class off a write and idempotent off a PUT or DELETE. */
export function operationBody(op: RestOperation, draft: OperationDraft): Record<string, unknown> {
  const overlay: Record<string, ParamOverlay> = {};
  for (const [name, entry] of Object.entries(draft.overlay)) {
    const out: ParamOverlay = {};
    if (entry.description.trim()) out.description = entry.description.trim();
    if (entry.hidden) out.hidden = true;
    if (entry.value.trim() !== "") out.value = coerceValue(entry.value, paramType(op, name));
    if (Object.keys(out).length) overlay[name] = out;
  }
  return {
    enabled: draft.enabled,
    llm_name: draft.llmName.trim(),
    llm_description: draft.llmDescription.trim(),
    ...(op.method.toUpperCase() === "POST" ? { read_only: draft.readOnly } : {}),
    params_overlay: overlay,
    grants: draft.grants.map((grant) => grantBody(op, grant)),
    response_select: draft.responseSelect.split(/[\n,]/).map((line) => line.trim()).filter(Boolean),
    ...answerBody(draft),
    ...(isReadDraft(op, draft) ? {} : { capability: draft.capability }),
    ...(idempotentAllowed(op.method) ? { idempotent: draft.idempotent } : {}),
  };
}

export const isReadDraft = (op: Pick<RestOperation, "method">, draft: Pick<OperationDraft, "readOnly">) => {
  const method = op.method.toUpperCase();
  return method === "GET" || method === "HEAD" || (method === "POST" && draft.readOnly);
};

export function bodyScopeMissingText(params: string[]): string {
  return `Scope on ${params.join(", ")} only: the model still writes the request body. If the API takes the target from the body, fix that field too (body scope).`;
}

export function grantWarning(grant: GrantDraft, write = false, hasBody = false): string | null {
  const params = grant.scope.filter((row) => row.param && row.value.trim() !== "").map((row) => row.param);
  if (!params.length) return null;
  if (write) {
    const bodyScoped = grant.bodyScope.some((row) => row.param.trim() && row.value.trim() !== "");
    return hasBody && !bodyScoped ? bodyScopeMissingText(params) : null;
  }
  if (grant.filterField.trim()) return null;
  return scopeWithoutFilterText(params);
}

export function operationWarnings(op: RestOperation, draft: OperationDraft, perGrant = true): string[] {
  const warnings: string[] = [];
  const write = !isReadDraft(op, draft);
  if (draft.enabled && !draft.grants.length) warnings.push(OFFERED_TO_NOBODY);
  for (const grant of perGrant ? draft.grants : []) {
    const warning = grantWarning(grant, write, hasRequestBody(op));
    if (warning) warnings.push(`${grant.role || "New grant"}: ${warning}`);
  }
  return warnings;
}

export const unsavedHint = (hint: string) => `Unsaved: ${hint}`;

const FIELD_PATH = /^[A-Za-z0-9_$@-]+(\.[A-Za-z0-9_$@-]+)*$/;

export type GrantProblems = { role?: string; scope?: string; bodyScope?: string; filter?: string };

export function grantProblems(grant: GrantDraft): GrantProblems {
  const problems: GrantProblems = {};
  if (!/^[A-Za-z0-9_.:-]{1,80}$/.test(grant.role.trim())) problems.role = "Name a role: letters, digits or _ . : - (up to 80).";
  if (grant.scope.some((row) => !row.param || row.value.trim() === "")) problems.scope = "Each scope line needs a parameter and a value.";
  const paths = grant.bodyScope.map((row) => row.param.trim());
  if (grant.bodyScope.some((row) => !row.param.trim() || row.value.trim() === "")) problems.bodyScope = "Each body line needs a field and a value.";
  else if (paths.some((path) => !FIELD_PATH.test(path))) problems.bodyScope = "A body field is a dotted path, e.g. assignment_group or group.id.";
  else if (new Set(paths).size !== paths.length) problems.bodyScope = "Each body field once.";
  const field = grant.filterField.trim();
  if (field && !FIELD_PATH.test(field)) problems.filter = "The field is a dotted path, e.g. group.id.";
  else if (field && grant.filterValue.trim() === "") problems.filter = "Give the value the field must equal.";
  else if (!field && grant.filterValue.trim() !== "") problems.filter = "Name the field the value is compared with.";
  return problems;
}

export const hasProblems = (problems: GrantProblems) => Object.keys(problems).length > 0;
