import type { AccessField } from "./connectionTypes";

// Mirrors the backend's per-mode field tables until the server marks auth_kinds per field; a server mark always wins.

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

export const authModeField = (fields: AccessField[]): AccessField | null =>
  fields.find((field) => field.key.endsWith("_auth_mode")) ?? null;

function fieldsOfMode(type: string, mode: string): Set<string> | null {
  const table = MODE_FIELDS[type];
  if (!table) return null;
  const fields = new Set(table[mode] ?? []);
  if (mode === ATLASSIAN_OIDC && (type === "jira" || type === "confluence" || type === "bitbucket")) fields.add(`${type}_oidc_*`);
  return fields;
}

function dependsOnMode(type: string, key: string): boolean {
  const table = MODE_FIELDS[type];
  if (!table) return false;
  if (Object.values(table).some((keys) => keys.includes(key))) return true;
  return key.includes("_oidc_");
}

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

export function visibleAccessFields(type: string, fields: AccessField[], values: Record<string, string>): AccessField[] {
  if (type === BITBUCKET) return bitbucketFields(fields, values);
  return byAuthKind(type, fields, values).filter((field) => applies(field, values));
}

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

const BITBUCKET_CLOUD_TEXTS: Record<string, { label: string; placeholder: string }> = {
  bitbucket_url: { label: "Bitbucket URL", placeholder: "https://bitbucket.org" },
  bitbucket_username: { label: "Atlassian account email", placeholder: "e.g. you@example.com" },
  bitbucket_token: { label: "Atlassian API token (with Bitbucket scopes)", placeholder: "" },
};

const cloudText = (type: string, key: string, values: Record<string, string>) =>
  (type === BITBUCKET && isBitbucketCloud(values) ? BITBUCKET_CLOUD_TEXTS[key] : undefined);

export function accessFieldText(type: string, field: AccessField, values: Record<string, string>): AccessField {
  const cloud = cloudText(type, field.key, values);
  return cloud ? { ...field, label: cloud.label, placeholder: cloud.placeholder || field.placeholder } : field;
}

export const accessLabel = (type: string, key: string, values: Record<string, string>, label: string) =>
  cloudText(type, key, values)?.label ?? label;

const BITBUCKET_DEPLOYMENT_LABELS: Record<string, string> = { cloud: "Bitbucket Cloud", datacenter: "Server / Data Center" };

export function accessOptionLabel(type: string, key: string, option: string): string | null {
  return type === BITBUCKET && key === BITBUCKET_DEPLOYMENT ? BITBUCKET_DEPLOYMENT_LABELS[option] ?? null : null;
}

export function accessFieldOptions(type: string, field: AccessField, values: Record<string, string>, options: string[]): string[] {
  if (type !== BITBUCKET || field.key !== BITBUCKET_MODE || isBitbucketCloud(values)) return options;
  return options.filter((option) => option !== BITBUCKET_CLOUD_MODE);
}

// Moving Bitbucket to Cloud clears the sign-in mode: the server refuses a Server/Data Center mode there.
export function withAccessValue(type: string, values: Record<string, string>, key: string, text: string): Record<string, string> {
  const next = { ...values, [key]: text };
  if (type !== BITBUCKET || key !== BITBUCKET_DEPLOYMENT) return next;
  const mode = next[BITBUCKET_MODE] ?? "";
  if (isBitbucketCloud(next) ? mode && mode !== BITBUCKET_CLOUD_MODE : mode === BITBUCKET_CLOUD_MODE) next[BITBUCKET_MODE] = "";
  return next;
}

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

export function lowerFirst(text: string): string {
  return /^[A-Z][a-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text;
}

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
