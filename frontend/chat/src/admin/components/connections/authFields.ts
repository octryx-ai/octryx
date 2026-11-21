import type { AccessField } from "./connectionTypes";

// Which access fields belong to which sign-in kind (show only the chosen kind's fields). The server's
// descriptor does not mark this per field yet, so the frontend mirrors the backend's own tables once, here:
// atlassian_auth.py _MODE_FIELDS (principal + secret per mode, OIDC adds every "<product>_oidc_*" field) and
// servicenow_auth.py _MODE_SECRETS / the OIDC field set. A field marked by the server (access_fields[].auth_kinds)
// always wins; a type not listed here shows every field.

type ModeFields = Record<string, string[]>;

const ATLASSIAN_OIDC = "oidc_client_credentials";

const MODE_FIELDS: Record<string, ModeFields> = {
  confluence: {
    cloud_api_token: ["confluence_username", "confluence_token"],
    basic: ["confluence_username", "confluence_password"],
    bearer_pat: ["confluence_token"],
    [ATLASSIAN_OIDC]: ["confluence_oidc_client_id", "confluence_oidc_client_secret"],
  },
  jira: {
    cloud_api_token: ["jira_email", "jira_token"],
    basic: ["jira_username", "jira_password"],
    bearer_pat: ["jira_token"],
    [ATLASSIAN_OIDC]: ["jira_oidc_client_id", "jira_oidc_client_secret"],
  },
  bitbucket: {
    cloud_api_token: ["bitbucket_username", "bitbucket_token"],
    basic: ["bitbucket_username", "bitbucket_password"],
    bearer_pat: ["bitbucket_token"],
    [ATLASSIAN_OIDC]: ["bitbucket_oidc_client_id", "bitbucket_oidc_client_secret"],
  },
  servicenow: {
    bearer_token: ["servicenow_token"],
    basic: ["servicenow_username", "servicenow_password"],
    oauth_password: [
      "servicenow_token_url", "servicenow_client_id", "servicenow_client_secret", "servicenow_username",
      "servicenow_password", "servicenow_oauth_scope",
    ],
    oidc_client_credentials: [
      "servicenow_token_url", "servicenow_client_id", "servicenow_client_secret", "servicenow_oauth_scope",
      "servicenow_oidc_audience", "servicenow_oidc_client_auth",
    ],
  },
};

/** The sign-in field of a type's access fields (the backend's "*_auth_mode"), if it has one. */
export const authModeField = (fields: AccessField[]): AccessField | null =>
  fields.find((field) => field.key.endsWith("_auth_mode")) ?? null;

function fieldsOfMode(type: string, mode: string): Set<string> | null {
  const table = MODE_FIELDS[type];
  if (!table) return null;
  const fields = new Set(table[mode] ?? []);
  // The Atlassian OIDC grant uses every "<product>_oidc_*" setting (token URL, scope, audience, client auth).
  if (mode === ATLASSIAN_OIDC && (type === "jira" || type === "confluence" || type === "bitbucket")) fields.add(`${type}_oidc_*`);
  return fields;
}

function dependsOnMode(type: string, key: string): boolean {
  const table = MODE_FIELDS[type];
  if (!table) return false;
  if (Object.values(table).some((keys) => keys.includes(key))) return true;
  return key.includes("_oidc_");
}

// Fields that apply only for one value of another field: ServiceNow's Scripted REST paths and page size only for the
// Scripted REST API style (backend services/servicenow_scripted.py; the Table API reads none of them).
const SCRIPTED_ONLY: [string, string] = ["servicenow_api_style", "scripted"];
const SHOWN_WHEN: Record<string, [string, string]> = {
  servicenow_incidents_path: SCRIPTED_ONLY,
  servicenow_changes_path: SCRIPTED_ONLY,
  servicenow_journal_path: SCRIPTED_ONLY,
  servicenow_page_size: SCRIPTED_ONLY,
};

const applies = (field: AccessField, values: Record<string, string>) => {
  const rule = SHOWN_WHEN[field.key];
  return !rule || (values[rule[0]] ?? "") === rule[1];
};

/**
 * The fields to show for the chosen sign-in kind: every field that does not depend on the kind, plus the kind's
 * own credential fields. Without a chosen kind only the independent fields (and the kind select) show. A field that
 * applies only for one value of another field (SHOWN_WHEN) shows only with that value.
 */
export function visibleAccessFields(type: string, fields: AccessField[], values: Record<string, string>): AccessField[] {
  if (type === BITBUCKET) return bitbucketFields(fields, values);
  return byAuthKind(type, fields, values).filter((field) => applies(field, values));
}

// ---- Bitbucket: where it runs decides the sign-in (backend atlassian_auth.py, named_connections/descriptors/scm.py)
// Cloud (bitbucket.org) signs in with the Atlassian account email and an API token only: no mode choice, Cloud texts.
// Server/Data Center chooses like Jira: user and password, an HTTP access token, or OpenID Connect client credentials;
// until a mode is chosen only the mode select and the fields independent of it show.

const BITBUCKET = "bitbucket";
const BITBUCKET_DEPLOYMENT = "bitbucket_deployment";
const BITBUCKET_MODE = "bitbucket_auth_mode";
const BITBUCKET_CLOUD_MODE = "cloud_api_token";

export const isBitbucketCloud = (values: Record<string, string>) =>
  (values[BITBUCKET_DEPLOYMENT] ?? "").trim().toLowerCase() === "cloud";

function bitbucketFields(fields: AccessField[], values: Record<string, string>): AccessField[] {
  const cloud = isBitbucketCloud(values);
  const mode = cloud ? BITBUCKET_CLOUD_MODE : values[BITBUCKET_MODE] ?? "";
  const own = mode ? fieldsOfMode(BITBUCKET, mode) : null;
  return fields.flatMap((field) => {
    if (field.key === BITBUCKET_MODE) return cloud ? [] : [field];
    if (!dependsOnMode(BITBUCKET, field.key)) return [field];
    return own?.has(field.key) || (field.key.startsWith("bitbucket_oidc_") && own?.has("bitbucket_oidc_*")) ? [field] : [];
  });
}

// Cloud's own words for the fields both deployments share; Server/Data Center keeps the server's labels.
const BITBUCKET_CLOUD_TEXTS: Record<string, { label: string; placeholder: string }> = {
  bitbucket_url: { label: "Bitbucket URL", placeholder: "https://bitbucket.org" },
  bitbucket_username: { label: "Atlassian account email", placeholder: "e.g. you@example.com" },
  bitbucket_token: { label: "Atlassian API token (with Bitbucket scopes)", placeholder: "" },
};

const cloudText = (type: string, key: string, values: Record<string, string>) =>
  (type === BITBUCKET && isBitbucketCloud(values) ? BITBUCKET_CLOUD_TEXTS[key] : undefined);

/** A field as the form shows it: Bitbucket Cloud's label and placeholder, else the server's. */
export function accessFieldText(type: string, field: AccessField, values: Record<string, string>): AccessField {
  const cloud = cloudText(type, field.key, values);
  return cloud ? { ...field, label: cloud.label, placeholder: cloud.placeholder || field.placeholder } : field;
}

/** A field's label by its key (forms over the named-connection descriptor): Bitbucket Cloud's, else `label`. */
export const accessLabel = (type: string, key: string, values: Record<string, string>, label: string) =>
  cloudText(type, key, values)?.label ?? label;

// Where Bitbucket runs, in the words of the form; other choices keep authLabel.
const BITBUCKET_DEPLOYMENT_LABELS: Record<string, string> = { cloud: "Bitbucket Cloud", datacenter: "Server / Data Center" };

/** The words for one choice of a select, or null to use the shared labels (authLabel). */
export function accessOptionLabel(type: string, key: string, option: string): string | null {
  return type === BITBUCKET && key === BITBUCKET_DEPLOYMENT ? BITBUCKET_DEPLOYMENT_LABELS[option] ?? null : null;
}

/** A select's choices for the current values: Server/Data Center offers no Cloud sign-in. */
export function accessFieldOptions(type: string, field: AccessField, values: Record<string, string>, options: string[]): string[] {
  if (type !== BITBUCKET || field.key !== BITBUCKET_MODE || isBitbucketCloud(values)) return options;
  return options.filter((option) => option !== BITBUCKET_CLOUD_MODE);
}

/**
 * The values after one field changed. Bitbucket: moving to Cloud clears the sign-in choice (Cloud has none; the server
 * refuses a Server/Data Center mode there), moving back leaves it to choose again.
 */
export function withAccessValue(type: string, values: Record<string, string>, key: string, text: string): Record<string, string> {
  const next = { ...values, [key]: text };
  if (type !== BITBUCKET || key !== BITBUCKET_DEPLOYMENT) return next;
  const mode = next[BITBUCKET_MODE] ?? "";
  if (isBitbucketCloud(next) ? mode && mode !== BITBUCKET_CLOUD_MODE : mode === BITBUCKET_CLOUD_MODE) next[BITBUCKET_MODE] = "";
  return next;
}

/** The sign-in kind a connection uses, also when it names none (a Bitbucket Cloud connection). */
export function effectiveAuthKind(type: string, auth: string, values: Record<string, string>): string {
  return !auth && type === BITBUCKET && isBitbucketCloud(values) ? BITBUCKET_CLOUD_MODE : auth;
}

function byAuthKind(type: string, fields: AccessField[], values: Record<string, string>): AccessField[] {
  const modeField = authModeField(fields);
  if (!modeField) return fields;
  const mode = values[modeField.key] ?? "";
  const marked = fields.some((field) => field.authKinds.length > 0);
  return fields.filter((field) => {
    if (field.key === modeField.key) return true;
    if (marked) return field.authKinds.length === 0 || field.authKinds.includes(mode);
    if (!dependsOnMode(type, field.key)) return true;
    const own = fieldsOfMode(type, mode);
    if (!own) return true;
    return own.has(field.key) || (own.has(`${type}_oidc_*`) && field.key.startsWith(`${type}_oidc_`));
  });
}

/** "Client secret" → "client secret"; a word in capitals ("HTTP access token") stays as it is. */
export function lowerFirst(text: string): string {
  return /^[A-Z][a-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

/** Readable names for the backend's sign-in kinds. */
export const AUTH_KIND_LABELS: Record<string, string> = {
  cloud_api_token: "Cloud: email and API token",
  basic: "User and password",
  bearer_pat: "Personal access token",
  bearer_token: "Bearer token",
  oidc_client_credentials: "OpenID Connect client credentials",
  oauth_password: "OAuth with user and password",
  token: "Token",
  none: "No sign-in",
};
