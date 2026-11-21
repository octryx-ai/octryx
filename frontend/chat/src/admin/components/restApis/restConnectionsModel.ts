// REST API model: connection drafts, request bodies and secret states.
import type { AuthScheme, PublicField, RestConnection, RestDefinition, SecretField } from "./restApisApi";
import { connectionAuthFields } from "./restAuthModel";

// ---- connections -------------------------------------------------------------------------------------------------

export type ConnectionDraft = {
  workspaceId: string;
  name: string;
  baseUrl: string;
  fields: Record<PublicField, string>;
  secrets: Record<SecretField, string>;
  clear: Record<SecretField, boolean>;
};

const PUBLIC_FIELDS: PublicField[] = ["username", "client_id", "token_url", "scope", "audience"];
const SECRET_FIELDS: SecretField[] = ["api_key", "token", "password", "client_secret"];

export function connectionDraft(connection: RestConnection | null, definition: Pick<RestDefinition, "servers">): ConnectionDraft {
  const fields = Object.fromEntries(PUBLIC_FIELDS.map((name) => [name, connection?.fields[name] ?? ""])) as Record<PublicField, string>;
  return {
    workspaceId: connection?.project_id ?? "",
    name: connection?.name ?? "",
    baseUrl: connection?.base_url ?? definition.servers[0] ?? "",
    fields,
    secrets: { api_key: "", token: "", password: "", client_secret: "" },
    clear: { api_key: false, token: false, password: false, client_secret: false },
  };
}

/**
 * The connection POST (new) or PUT (existing). Only the scheme's fields are sent; a typed secret replaces the stored
 * one, a cleared one sends clear_<field>, an untouched one is left out (secrets are write-only).
 */
export function connectionBody(draft: ConnectionDraft, scheme: AuthScheme, existing: RestConnection | null): Record<string, unknown> {
  const body: Record<string, unknown> = { name: draft.name.trim(), base_url: draft.baseUrl.trim() };
  if (!existing) body.project_id = draft.workspaceId || null;
  if (existing && !body.name) delete body.name;
  for (const field of connectionAuthFields(scheme)) {
    if (!field.secret) {
      const value = draft.fields[field.name as PublicField].trim();
      if (value || existing) body[field.name] = value;
      continue;
    }
    const name = field.name as SecretField;
    const value = draft.secrets[name].trim();
    if (value) body[name] = value;
    else if (existing && draft.clear[name]) body[`clear_${name}`] = true;
  }
  return body;
}

export type SecretState = "set" | "not_set" | "replace" | "clear";

export function secretState(connection: RestConnection | null, draft: ConnectionDraft, name: SecretField): SecretState {
  if (draft.secrets[name].trim()) return "replace";
  if (connection && draft.clear[name]) return "clear";
  return connection?.secret_status[name] ? "set" : "not_set";
}

export const SECRET_STATE_WORDS: Record<SecretState, string> = {
  set: "Set",
  not_set: "Not set",
  replace: "Will be replaced on save",
  clear: "Will be cleared on save",
};

export const connectionOwnerText = (connection: Pick<RestConnection, "project_id">, workspaceName: (id: string) => string) =>
  connection.project_id ? `Workspace ${workspaceName(connection.project_id)}` : "Platform";

const FIELD_LABELS: Record<string, string> = {
  api_key: "API key", token: "token", password: "password", client_secret: "client secret", username: "user name", client_id: "client ID",
};

export function missingText(connection: Pick<RestConnection, "missing_for_auth">): string | null {
  if (!connection.missing_for_auth.length) return null;
  return `Missing for the API's authentication: ${connection.missing_for_auth.map((name) => FIELD_LABELS[name] ?? name).join(", ")}.`;
}
