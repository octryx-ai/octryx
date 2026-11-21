import { AUTH_KIND_LABELS } from "./authFields";

// The kinds of connection the server knows (GET /api/v1/admin/connection-types, from the backend's connector
// descriptors): label, sign-in kinds, access fields and which uses a type offers.
// No fixed list lives in the frontend; without descriptors the page falls back to readable names only.

// kind is the descriptor's field kind: text | url | select (options; an empty list on the sign-in field means the
// type's auth_kinds) | secret (write-only) | bool | list | int (a whole number).
// authKinds: the sign-in kinds a field belongs to when the server marks it (access_fields[].auth_kinds); [] = always.
// placeholder: the server's example value for the input (access_fields[].placeholder), if any.
export type AccessField = {
  key: string; label: string; required: boolean; secret: boolean; kind: string; options: string[]; authKinds: string[];
  placeholder?: string;
};
// The keys a connection binds (bound_scopes) for a type whose descriptor has an allowlist (binding): their name, case
// and what the Workspace's own list (allowlistField) means while empty (servesUnlisted: every key; else none).
export type Binding = {
  label: string; plural: string; example: string; upper: boolean; pattern: string; allowlistField: string; servesUnlisted: boolean;
};
export type UseKind = "knowledge" | "tickets" | "agent_tools" | "repositories";
export type TicketState = { key: string; label: string };
export type ConnectionType = {
  type: string; label: string; authKinds: string[]; accessFields: AccessField[]; uses: UseKind[];
  // The key a Knowledge scope uses for this type (top-level scope_key: projects, spaces, tables, repositories);
  // "" when the server sends null: then the type has no scope to edit.
  scopeKey: string;
  // Our ticket states (ticket_states, the server's workflow states): the only values "Here" may take.
  ticketStates: TicketState[];
  // Whether the server can test this type's access (testable); false hides "Test".
  testable: boolean;
  // null: the type binds no keys (no "… this connection serves" editor).
  binding: Binding | null;
};

type Rec = Record<string, unknown>;
const rec = (value: unknown): Rec | null => (value && typeof value === "object" && !Array.isArray(value) ? value as Rec : null);
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const USES: UseKind[] = ["knowledge", "tickets", "agent_tools", "repositories"];

export const humanize = (value: string) => (value ? value.charAt(0).toUpperCase() + value.slice(1).replace(/[_-]+/g, " ") : "");

function readBinding(value: unknown): Binding | null {
  const row = rec(value);
  const plural = str(row?.plural), field = str(row?.allowlist_field);
  if (!row || !plural || !field) return null;
  return { label: str(row.label) || plural, plural, example: str(row.example), upper: str(row.case) !== "lower" && str(row.case) !== "exact",
    pattern: str(row.pattern), allowlistField: field, servesUnlisted: row.serves_unlisted !== false };
}

export function readConnectionTypes(payload: unknown): ConnectionType[] {
  // The endpoint answers a bare array (backend connections/catalog.py).
  const entries = list(payload);
  return entries.map((entry) => {
    const row = rec(entry);
    const type = str(row?.type);
    if (!row || !type) return null;
    const uses = list(row.uses).map(str).filter((use): use is UseKind => USES.includes(use as UseKind));
    return {
      type, label: str(row.label) || humanize(type),
      authKinds: list(row.auth_kinds).map(str).filter(Boolean),
      accessFields: list(row.access_fields).map((field): AccessField | null => {
        const value = rec(field);
        return value && str(value.key) ? { key: str(value.key), label: str(value.label) || humanize(str(value.key)),
          required: value.required === true, secret: value.secret === true || value.kind === "secret",
          kind: str(value.kind) || "text", options: list(value.options).map(str).filter(Boolean),
          authKinds: list(value.auth_kinds).map(str).filter(Boolean), placeholder: str(value.placeholder) } : null;
      }).filter((field): field is AccessField => field !== null),
      uses,
      scopeKey: str(row.scope_key),
      ticketStates: list(row.ticket_states).map((entry) => {
        const value = rec(entry);
        return value && str(value.key) ? { key: str(value.key), label: str(value.label) || humanize(str(value.key)) } : null;
      }).filter((entry): entry is TicketState => entry !== null),
      testable: row.testable !== false,
      binding: readBinding(row.binding),
    };
  }).filter((entry): entry is ConnectionType => entry !== null);
}

/** Access fields when the server sends no descriptor for a type: address, account and one secret. */
export const FALLBACK_ACCESS_FIELDS: AccessField[] = [
  { key: "base_url", label: "Address", required: false, secret: false, kind: "url", options: [], authKinds: [] },
  { key: "account", label: "Account", required: false, secret: false, kind: "text", options: [], authKinds: [] },
  { key: "secret", label: "Secret", required: false, secret: true, kind: "secret", options: [], authKinds: [] },
];

/** A select field's choices: its own options, else (the sign-in field) the type's auth_kinds. */
export const fieldOptions = (field: AccessField, descriptor: ConnectionType | null) =>
  field.options.length ? field.options : field.kind === "select" ? descriptor?.authKinds ?? [] : [];

/** Whether "Test" is offered: the type's testable flag (true without a descriptor). */
export const isTestable = (type: string, types: ConnectionType[] = []) => findType(types, type)?.testable ?? true;

export const findType = (types: ConnectionType[], type: string) => types.find((entry) => entry.type === type) ?? null;
export const typeLabel = (type: string, types: ConnectionType[] = []) => findType(types, type)?.label ?? humanize(type);
export const accessFieldsOf = (descriptor: ConnectionType | null) =>
  descriptor && descriptor.accessFields.length ? descriptor.accessFields : FALLBACK_ACCESS_FIELDS;

/** Git types offer repositories; the descriptor says so, otherwise the documented git types. */
export function isGitType(type: string, types: ConnectionType[] = []): boolean {
  const descriptor = findType(types, type);
  if (descriptor) return descriptor.uses.includes("repositories");
  return ["bitbucket", "github", "gitlab", "git_repository"].includes(type);
}

/** The scope key of a type's Knowledge use (scope_key; "" = no scope editor). */
export const scopeKeyOf = (type: string, types: ConnectionType[] = []) => findType(types, type)?.scopeKey ?? "";

/** The keys a type's connection binds; null when the type binds none. */
export const bindingOf = (type: string, types: ConnectionType[] = []) => findType(types, type)?.binding ?? null;

/** Our ticket states a type maps to; empty when the server sends none (then "Here" stays free text). */
export const ticketStatesOf = (type: string, types: ConnectionType[] = []) => findType(types, type)?.ticketStates ?? [];

const AUTH_LABELS: Record<string, string> = {
  api_token: "API token", oauth: "OAuth", basic: "User and password", none: "No sign-in", pat: "Personal access token",
  token: "Token", bearer: "Bearer token", cloud: "Cloud", server: "Server / Data Center", datacenter: "Server / Data Center",
  table: "Table API", scripted: "Scripted REST API",
  // How an OpenID Connect client sends its secret to the token endpoint (backend oidc_client_credentials.py).
  client_secret_post: "Client secret in the request body", client_secret_basic: "HTTP Basic authentication",
};
export const authLabel = (auth: string) => AUTH_KIND_LABELS[auth] ?? AUTH_LABELS[auth] ?? (humanize(auth) || "—");

// The schedules the server keeps. "off" is "manual"; there is no every_5_min. "custom" goes with schedule_cron
// (five fields, at most every 15 minutes; 422 schedule_cron_invalid).
export const SCHEDULES = ["manual", "every_15_min", "hourly", "every_4_hours", "daily_0600", "custom"] as const;
const SCHEDULE_LABELS: Record<string, string> = {
  manual: "Manual", off: "Manual", every_15_min: "Every 15 minutes", hourly: "Hourly", every_4_hours: "Every 4 hours",
  daily_0600: "Daily at 06:00", custom: "Custom",
};

export function scheduleText(schedule: string): string {
  if (!schedule) return "—";
  return SCHEDULE_LABELS[schedule] ?? humanize(schedule);
}

/** The options of a schedule select: the server's set, plus the current value when it is outside it. */
export function scheduleOptions(current: string): string[] {
  const value = current === "off" ? "manual" : current;
  return !value || (SCHEDULES as readonly string[]).includes(value) ? [...SCHEDULES] : [value, ...SCHEDULES];
}

/** "TEAM, OPS" or one per line → ["TEAM", "OPS"]: a scope list as people type it. */
export function splitValues(text: string): string[] {
  return Array.from(new Set(text.split(/[,;\n]/).map((part) => part.trim()).filter(Boolean)));
}
