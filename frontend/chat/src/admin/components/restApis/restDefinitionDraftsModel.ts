import type { AuthScheme, OdataTemplate, RestDefinition, RestParameter } from "./restApisApi";
import { definitionAuthFields } from "./restAuthModel";
import { CSRF_HEADER } from "./restOdataModel";

export type ImportDraft = { key: string; name: string; source: "text" | "url"; specText: string; specUrl: string };

export function importBody(draft: ImportDraft): Record<string, unknown> {
  const body: Record<string, unknown> = { key: draft.key.trim() };
  if (draft.name.trim()) body.name = draft.name.trim();
  if (draft.source === "url") body.spec_url = draft.specUrl.trim();
  else body.spec_text = draft.specText;
  return body;
}

export type ManualDraft = {
  key: string;
  name: string;
  servers: string;
  scheme: AuthScheme;
  headerName: string;
  queryName: string;
  tokenUrl: string;
  scopes: string;
  timeout: string;
  csrf: boolean;
  csrfHeader?: string;
  csrfFetchPath?: string;
};

export const emptyManualDraft = (): ManualDraft => ({
  key: "", name: "", servers: "", scheme: "none", headerName: "", queryName: "", tokenUrl: "", scopes: "", timeout: "30", csrf: false,
  csrfHeader: "", csrfFetchPath: "",
});

const lines = (value: string) => value.split(/[\n,]/).map((line) => line.trim()).filter(Boolean);

export function manualBody(draft: ManualDraft): Record<string, unknown> {
  const auth: Record<string, unknown> = { scheme: draft.scheme };
  const fields = definitionAuthFields(draft.scheme);
  if (fields.includes("header_name") && draft.headerName.trim()) auth.header_name = draft.headerName.trim();
  if (fields.includes("query_name") && draft.queryName.trim()) auth.query_name = draft.queryName.trim();
  if (fields.includes("token_url") && draft.tokenUrl.trim()) auth.token_url = draft.tokenUrl.trim();
  if (fields.includes("scopes") && lines(draft.scopes.replace(/\s+/g, ",")).length) auth.scopes = lines(draft.scopes.replace(/\s+/g, ","));
  if (draft.csrf && draft.scheme !== "none") auth.csrf = csrfBody(draft);
  return {
    key: draft.key.trim(),
    name: draft.name.trim() || draft.key.trim(),
    servers: lines(draft.servers),
    auth,
    timeout_seconds: draft.timeout.trim() === "" ? 30 : Number(draft.timeout),
  };
}

export function csrfBody(draft: Pick<ManualDraft, "csrfHeader" | "csrfFetchPath">): Record<string, unknown> {
  const fetchPath = (draft.csrfFetchPath ?? "").trim();
  return { fetch: true, header: (draft.csrfHeader ?? "").trim() || CSRF_HEADER, ...(fetchPath ? { fetch_path: fetchPath } : {}) };
}

export type DefinitionEditDraft = Omit<ManualDraft, "key"> & { defaultPreset?: OdataTemplate | "" };

export function definitionEditDraft(
  definition: Pick<RestDefinition, "name" | "servers" | "auth" | "timeout_seconds" | "default_preset">,
): DefinitionEditDraft {
  return {
    name: definition.name,
    servers: definition.servers.join("\n"),
    scheme: definition.auth.scheme,
    headerName: definition.auth.header_name ?? "",
    queryName: definition.auth.query_name ?? "",
    tokenUrl: definition.auth.token_url ?? "",
    scopes: (definition.auth.scopes ?? []).join(" "),
    timeout: String(definition.timeout_seconds),
    csrf: Boolean(definition.auth.csrf?.fetch),
    csrfHeader: definition.auth.csrf?.header ?? "",
    csrfFetchPath: definition.auth.csrf?.fetch_path ?? "",
    ...(definition.default_preset === undefined ? {} : { defaultPreset: definition.default_preset }),
  };
}

// An unchanged scheme keeps source_scheme: the server replaces the whole auth block.
export function definitionEditBody(definition: Pick<RestDefinition, "auth">, draft: DefinitionEditDraft): Record<string, unknown> {
  const { defaultPreset, ...fields } = draft;
  const body = manualBody({ ...fields, key: "" });
  delete body.key;
  body.name = draft.name.trim();
  const source = definition.auth.source_scheme;
  const auth = body.auth as Record<string, unknown>;
  if (source && draft.scheme === definition.auth.scheme) auth.source_scheme = source;
  if (defaultPreset !== undefined) body.default_preset = defaultPreset;
  return body;
}

export const schemeChanged = (definition: Pick<RestDefinition, "auth">, draft: Pick<DefinitionEditDraft, "scheme">) =>
  draft.scheme !== definition.auth.scheme;

export type ManualOperationDraft = { opKey: string; method: string; path: string; summary: string; query: string };

export function manualOperationBody(draft: ManualOperationDraft): Record<string, unknown> {
  const path = draft.path.trim();
  const pathParams = [...path.matchAll(/\{([^}]+)\}/g)].map((match) => match[1]);
  const parameters: Array<Pick<RestParameter, "name" | "in" | "required">> = [
    ...pathParams.map((name) => ({ name, in: "path" as const, required: true })),
    ...lines(draft.query).filter((name) => !pathParams.includes(name)).map((name) => ({ name, in: "query" as const, required: false })),
  ];
  return { op_key: draft.opKey.trim(), method: draft.method, path, summary: draft.summary.trim(), parameters };
}
