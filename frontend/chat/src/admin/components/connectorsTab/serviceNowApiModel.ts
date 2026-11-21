import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import type { OidcFieldError } from "./oidcClientCredentialsModel";
import { serviceNowAuthView } from "./serviceNowAuthModel";
import type { ServiceNowAuthView } from "./serviceNowAuthModel";

// Which ServiceNow API the connector reads. Pure: no requests, no React.
//
// API contract: `servicenow_api_style` is `table` (default, today's behaviour: /api/now/table/*) or
// `scripted` (the customer's Scripted REST API). For `scripted`: `servicenow_incidents_path` and/or
// `servicenow_changes_path` (at least one; each beginning with /api/, no scheme, host, `..` or query), optional
// `servicenow_journal_path`, and `servicenow_page_size` (default 100, max 200). Nothing about the customer's API
// (namespace, API id, resource names) is built in: the admin enters the paths.

export type ServiceNowApiStyle = "table" | "scripted";

export const API_STYLE_FIELD = "servicenow_api_style";
export const PAGE_SIZE_FIELD = "servicenow_page_size";
export const PAGE_SIZE_DEFAULT = 100;
export const PAGE_SIZE_MAX = 200;
// The backend's path rule (services/servicenow_scripted.py): /api/ then letters, digits and _ . ~ / - only, at most 300.
const PATH_PATTERN = /^\/api\/[A-Za-z0-9_.~/-]+$/;
const PATH_MAX_CHARS = 300;

export type ScriptedPath = { field: string; label: string; placeholder: string; endpoint: string };

export const SCRIPTED_PATHS: readonly ScriptedPath[] = [
  { field: "servicenow_incidents_path", label: "Incidents path", placeholder: "/api/<namespace>/<api>/incidents", endpoint: "incidents" },
  { field: "servicenow_changes_path", label: "Changes path", placeholder: "/api/<namespace>/<api>/changes", endpoint: "changes" },
  { field: "servicenow_journal_path", label: "Journal path (optional)", placeholder: "/api/<namespace>/<api>/journal", endpoint: "journal" },
];

export const API_STYLE_TEXT: Record<ServiceNowApiStyle, { label: string; help: string }> = {
  table: {
    label: "Standard Table API",
    help: "Reads the tables directly (/api/now/table/…). The integration user needs read access to those tables.",
  },
  scripted: {
    label: "Custom Scripted REST API",
    help: "Reads incidents and changes through your organisation's Scripted REST endpoints. Enter the paths from your integration documentation; the generic table tools are not available then.",
  },
};

/** Every field the API section owns, so the generic panel and save loop leave them alone. */
export function serviceNowApiOwnedFields(): string[] {
  return [API_STYLE_FIELD, ...SCRIPTED_PATHS.map((path) => path.field), PAGE_SIZE_FIELD];
}

const text = (value: unknown) => (typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "");

/** The chosen style: the draft's value, else the stored one, else `table` (the default, today's behaviour). */
export function serviceNowApiStyle(connector: AdminConnector, draft: Record<string, string>): ServiceNowApiStyle {
  const value = text(draft[API_STYLE_FIELD]) || text(connector.public_fields?.[API_STYLE_FIELD]);
  return value === "scripted" ? "scripted" : "table";
}

/** Why a Scripted REST path cannot be used, or null. Only a path on the instance: /api/…, no scheme, host, `..` or query. */
export function scriptedPathProblem(value: string): string | null {
  if (/^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith("//")) {
    return "Enter only the path, without https:// or a host; the instance URL above is used.";
  }
  if (!value.startsWith("/api/")) return "The path must begin with /api/.";
  if (/[?#]/.test(value)) return "Remove the query string or fragment; paging is added by the connector.";
  if (value.includes("..") || value.slice(1).includes("//")) return "The path must not contain \"..\" or \"//\".";
  if (value.length > PATH_MAX_CHARS) return `The path is longer than ${PATH_MAX_CHARS} characters.`;
  if (!PATH_PATTERN.test(value)) return "Use only letters, digits and _ . ~ / - in the path (no spaces or placeholders).";
  return null;
}

/** Why a page size cannot be used, or null; empty means the default. */
export function pageSizeProblem(value: string): string | null {
  if (!value) return null;
  if (!/^\d+$/.test(value)) return "Enter a whole number.";
  const size = Number(value);
  if (size < 1 || size > PAGE_SIZE_MAX) return `Enter a page size between 1 and ${PAGE_SIZE_MAX}.`;
  return null;
}

export type ServiceNowApiView = { style: ServiceNowApiStyle; errors: Record<string, OidcFieldError> };

export function serviceNowApiView(connector: AdminConnector, draft: Record<string, string>): ServiceNowApiView {
  const style = serviceNowApiStyle(connector, draft);
  const errors: Record<string, OidcFieldError> = {};
  if (style === "scripted") {
    for (const path of SCRIPTED_PATHS) {
      const value = text(draft[path.field]);
      const problem = value ? scriptedPathProblem(value) : null;
      if (problem) errors[path.field] = { message: problem, live: true };
    }
    // At least one list endpoint: incidents or changes (the journal alone lists nothing).
    if (!text(draft[SCRIPTED_PATHS[0].field]) && !text(draft[SCRIPTED_PATHS[1].field])) {
      errors[SCRIPTED_PATHS[0].field] = { message: "Enter the incidents path, the changes path or both.", live: false };
    }
    const problem = pageSizeProblem(text(draft[PAGE_SIZE_FIELD]));
    if (problem) errors[PAGE_SIZE_FIELD] = { message: problem, live: true };
  }
  return { style, errors };
}

/**
 * The API part of the save body. The style is sent once chosen or stored; with `scripted` the paths and the page size follow (an
 * optional path or page size that was stored and is now cleared is sent as ""). With `table` the stored paths are left
 * as they are (they are ignored for the Table API).
 */
export function serviceNowApiSaveFields(connector: AdminConnector, draft: Record<string, string>): Record<string, unknown> {
  // Nothing chosen and nothing stored: the default (Table API) stays implicit, so an untouched save changes nothing.
  if (!text(draft[API_STYLE_FIELD]) && !text(connector.public_fields?.[API_STYLE_FIELD])) return {};
  const style = serviceNowApiStyle(connector, draft);
  const body: Record<string, unknown> = { [API_STYLE_FIELD]: style };
  if (style !== "scripted") return body;
  for (const field of [...SCRIPTED_PATHS.map((path) => path.field), PAGE_SIZE_FIELD]) {
    const value = text(draft[field]);
    if (value) body[field] = field === PAGE_SIZE_FIELD ? Number(value) : value;
    else if (text(connector.public_fields?.[field])) body[field] = "";
  }
  return body;
}

// ---- connection test per endpoint ----------------------------------------------------------------

export type EndpointResult = { endpoint: string; label: string; ok: boolean; text: string };

const ENDPOINT_LABEL: Record<string, string> = { incidents: "Incidents", changes: "Changes", journal: "Journal" };

// The backend's closed endpoint codes (services/servicenow_scripted.py).
const ENDPOINT_CODE_TEXT: Record<string, string> = {
  servicenow_endpoint_http_status: "the endpoint answered with an error status",
  servicenow_endpoint_empty_answer: "the endpoint answered without content",
  servicenow_endpoint_unexpected_shape: "the answer has no single record list under result; check that the path is the list endpoint",
  servicenow_endpoint_unreachable: "the endpoint could not be reached; check the path and the egress policy",
  servicenow_endpoint_not_configured: "no path is configured for this endpoint",
  servicenow_table_api_disabled: "this connection uses the Scripted REST API; the table tools are not available",
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/**
 * The per-endpoint lines of a Scripted REST connection test. Read from `endpoints`: a list of
 * `{endpoint, ok, total?, code?, http_status?, summary?}` or a map `{<endpoint>: {...}}`. Empty when the test has none.
 */
export function endpointResults(result: unknown): EndpointResult[] {
  if (!isRecord(result)) return [];
  const raw = result.endpoints;
  const entries: [string, unknown][] = Array.isArray(raw)
    ? raw.map((entry) => [isRecord(entry) ? text(entry.endpoint) || text(entry.name) : "", entry])
    : isRecord(raw) ? Object.entries(raw) : [];
  return entries.filter(([name, entry]) => name && isRecord(entry)).map(([name, entry]) => {
    const record = entry as Record<string, unknown>;
    const label = ENDPOINT_LABEL[name] ?? name;
    if (record.ok === true) {
      const total = typeof record.total === "number" ? record.total : null;
      return { endpoint: name, label, ok: true, text: total === null ? "OK" : `OK, ${total} ${total === 1 ? "record" : "records"} in total` };
    }
    const code = text(record.code);
    const status = typeof record.http_status === "number" ? record.http_status : typeof record.status === "number" ? record.status : null;
    const why = ENDPOINT_CODE_TEXT[code] || text(record.summary) || (code ? `refused (${code})` : "failed");
    return { endpoint: name, label, ok: false, text: status === null ? why : `${why} (HTTP ${status})` };
  });
}

// ---- the whole ServiceNow setup ------------------------------------------------------------------

export type ServiceNowSetupView = { auth: ServiceNowAuthView; api: ServiceNowApiView; errors: Record<string, OidcFieldError> };

/** Sign-in and API section together: the card stops a save while either has an error. */
export function serviceNowSetupView(connector: AdminConnector, draft: Record<string, string>): ServiceNowSetupView {
  const auth = serviceNowAuthView(connector, draft);
  const api = serviceNowApiView(connector, draft);
  return { auth, api, errors: { ...auth.errors, ...api.errors } };
}
