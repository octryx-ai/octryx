import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import {
  OIDC_TEXT,
  SERVICENOW_OIDC_FIELDS,
  isLoopbackHost,
  oidcSaveFields,
  oidcSettingErrors,
  oidcSettingFields,
} from "./oidcClientCredentialsModel";
import type { OidcFieldError } from "./oidcClientCredentialsModel";

// How the ServiceNow connector signs in (extension). Pure: no requests, no React.
//
// Frozen contract: the non-secret preset field `servicenow_auth_mode` is one of
// - `oidc_client_credentials`: a token from the identity provider (servicenow_token_url, servicenow_client_id,
//   secret servicenow_client_secret, optional servicenow_oauth_scope, servicenow_oidc_audience,
//   servicenow_oidc_client_auth);
// - `oauth_password`: ServiceNow's own OAuth with the password grant (servicenow_token_url, servicenow_client_id,
//   secret servicenow_client_secret, servicenow_username, secret servicenow_password, optional servicenow_oauth_scope);
// - `bearer_token`: a stored bearer token (secret servicenow_token);
// - `basic`: servicenow_username and the secret servicenow_password.
// Only the explicit mode's credentials are used. A connector without a saved mode cannot be saved until the admin
// picks a method.

export type ServiceNowAuthMode = "oidc_client_credentials" | "oauth_password" | "bearer_token" | "basic";
export type StoredServiceNowMode = ServiceNowAuthMode | "none" | "unknown";

export const SERVICENOW_AUTH_MODE_FIELD = "servicenow_auth_mode";
export const SERVICENOW_URL_FIELD = "servicenow_url";
export const SERVICENOW_AUTH_MODES: readonly ServiceNowAuthMode[] = ["oidc_client_credentials", "oauth_password", "bearer_token", "basic"];

export type FieldSpec = { field: string; label: string };
type ModeSpec = { label: string; help: string; principals: FieldSpec[]; secrets: FieldSpec[] };
export type ServiceNowModeFields = ModeSpec & {
  principal: string | null;
  secret: string;
  principalLabel: string;
  secretLabel: string;
};

const CLIENT_ID: FieldSpec = { field: SERVICENOW_OIDC_FIELDS.clientId, label: OIDC_TEXT.clientIdLabel };
const CLIENT_SECRET: FieldSpec = { field: SERVICENOW_OIDC_FIELDS.clientSecret, label: OIDC_TEXT.clientSecretLabel };
const USERNAME: FieldSpec = { field: "servicenow_username", label: "Username" };
const PASSWORD: FieldSpec = { field: "servicenow_password", label: "Password" };

const MODES: Record<ServiceNowAuthMode, ModeSpec> = {
  oidc_client_credentials: {
    label: "OpenID Connect / OAuth client credentials",
    help: "A client registered in your identity provider or in ServiceNow: token endpoint, client id and client secret. Tokens are requested and renewed by the connector.",
    principals: [CLIENT_ID],
    secrets: [CLIENT_SECRET],
  },
  oauth_password: {
    label: "OAuth (username and password)",
    help: "ServiceNow's own OAuth with the password grant: an OAuth client (id and secret) plus the integration user's username and password. Tokens are requested and renewed by the connector.",
    principals: [CLIENT_ID, USERNAME],
    secrets: [CLIENT_SECRET, PASSWORD],
  },
  bearer_token: {
    label: "Bearer token",
    help: "An access token issued for the connector; it is sent as is until it is replaced here.",
    principals: [],
    secrets: [{ field: "servicenow_token", label: "Bearer token" }],
  },
  basic: {
    label: "Username and password",
    help: "A ServiceNow account's username and password (Basic authentication).",
    principals: [USERNAME],
    secrets: [PASSWORD],
  },
};

/** A method's fields; `principal`/`secret` name the first of each (the single-credential methods' only ones). */
export function serviceNowModeFields(mode: ServiceNowAuthMode): ServiceNowModeFields {
  const spec = MODES[mode];
  return {
    ...spec,
    principal: spec.principals[0]?.field ?? null,
    principalLabel: spec.principals[0]?.label ?? "",
    secret: spec.secrets[0].field,
    secretLabel: spec.secrets[0].label,
  };
}

/** The methods that request a token at `servicenow_token_url`. */
export function usesTokenUrl(mode: ServiceNowAuthMode | null): boolean {
  return mode === "oidc_client_credentials" || mode === "oauth_password";
}

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const isMode = (value: unknown): value is ServiceNowAuthMode =>
  typeof value === "string" && (SERVICENOW_AUTH_MODES as readonly string[]).includes(value);

const CREDENTIAL_PRINCIPALS = ["servicenow_client_id", "servicenow_username"];
const CREDENTIAL_SECRETS = ["servicenow_client_secret", "servicenow_token", "servicenow_password"];

/** Every field the guided sign-in owns, so the generic panel and save loop leave them alone. */
export function serviceNowOwnedFields(): string[] {
  return Array.from(new Set([
    SERVICENOW_URL_FIELD,
    SERVICENOW_AUTH_MODE_FIELD,
    ...CREDENTIAL_PRINCIPALS,
    ...CREDENTIAL_SECRETS,
    ...oidcSettingFields(SERVICENOW_OIDC_FIELDS),
  ]));
}

export function storedServiceNowMode(connector: AdminConnector): StoredServiceNowMode {
  const raw = connector.public_fields?.[SERVICENOW_AUTH_MODE_FIELD];
  if (isMode(raw)) return raw;
  return raw !== undefined && raw !== null && raw !== "" ? "unknown" : "none";
}

export type ServiceNowAuthView = {
  stored: StoredServiceNowMode;
  mode: ServiceNowAuthMode | null;
  switching: boolean;
  /** Whether the first secret of the method may be left blank (kept). */
  secretKeepable: boolean;
  /** Per secret field of the method: leaving it blank keeps the stored one. */
  keepable: Record<string, boolean>;
  errors: Record<string, OidcFieldError>;
};

/** Why a ServiceNow instance URL cannot be used, or null. */
export function serviceNowUrlProblem(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return "Enter the full instance URL, starting with https://.";
  }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && isLoopbackHost(url.hostname))) {
    return "The ServiceNow URL must start with https:// (http only for a local test instance).";
  }
  if (url.username || url.password) return "Remove the user name or password from the URL; enter credentials in the fields below.";
  if (url.search || url.hash) return "Remove the query string or fragment from the ServiceNow URL.";
  return null;
}

/** The instance's own token endpoint, `<instance URL>/oauth_token.do`, as a prefill for the password grant; null for
 * an unusable instance URL. Nothing else is assumed: the admin can change it. */
export function defaultServiceNowTokenUrl(instanceUrl: string): string | null {
  const value = text(instanceUrl);
  if (!value || serviceNowUrlProblem(value)) return null;
  return `${value.replace(/\/+$/, "")}/oauth_token.do`;
}

export function serviceNowAuthView(connector: AdminConnector, draft: Record<string, string>): ServiceNowAuthView {
  const stored = storedServiceNowMode(connector);
  const chosen = text(draft[SERVICENOW_AUTH_MODE_FIELD]);
  const mode = isMode(chosen) ? chosen : null;
  const switching = Boolean(mode) && (stored === "unknown" || (isMode(stored) && stored !== mode));
  const errors: Record<string, OidcFieldError> = {};
  const keepable: Record<string, boolean> = {};

  const url = text(draft[SERVICENOW_URL_FIELD]);
  if (!url) errors[SERVICENOW_URL_FIELD] = { message: "Enter the ServiceNow instance URL.", live: false };
  else {
    const problem = serviceNowUrlProblem(url);
    if (problem) errors[SERVICENOW_URL_FIELD] = { message: problem, live: true };
  }

  if (!mode) {
    if (stored === "unknown") {
      errors[SERVICENOW_AUTH_MODE_FIELD] = { message: "The saved sign-in method is not recognised. Choose one before saving.", live: true };
    } else {
      errors[SERVICENOW_AUTH_MODE_FIELD] = { message: "Choose how ServiceNow signs in.", live: false };
    }
  } else {
    const spec = MODES[mode];
    // Both token methods validate the token URL the same way (https, loopback http for tests, no user info).
    if (usesTokenUrl(mode)) Object.assign(errors, oidcSettingErrors(SERVICENOW_OIDC_FIELDS, draft));
    for (const principal of spec.principals) {
      if (!text(draft[principal.field])) errors[principal.field] = { message: `Enter the ${principal.label.toLowerCase()}.`, live: false };
    }
    for (const secret of spec.secrets) {
      keepable[secret.field] = Boolean(connector.secret_status?.[secret.field]) && !switching;
      if (!text(draft[secret.field]) && !keepable[secret.field]) {
        errors[secret.field] = {
          message: switching
            ? `Enter a new ${secret.label.toLowerCase()}: the sign-in method changes, so the stored secret is not reused.`
            : `Enter the ${secret.label.toLowerCase()}.`,
          live: false,
        };
      }
    }
  }
  const first = mode ? MODES[mode].secrets[0].field : "";
  return { stored, mode, switching, secretKeepable: Boolean(keepable[first]), keepable, errors };
}

/** The sign-in part of the save body: the URL and the chosen method's fields, never another method's. */
export function serviceNowAuthSaveFields(connector: AdminConnector, draft: Record<string, string>): Record<string, unknown> {
  const view = serviceNowAuthView(connector, draft);
  const body: Record<string, unknown> = {};
  const url = text(draft[SERVICENOW_URL_FIELD]);
  if (url) body[SERVICENOW_URL_FIELD] = url;
  if (!view.mode) return body;
  body[SERVICENOW_AUTH_MODE_FIELD] = view.mode;
  if (view.mode === "oidc_client_credentials") {
    return { ...body, ...oidcSaveFields(SERVICENOW_OIDC_FIELDS, draft, connector.public_fields) };
  }
  const spec = MODES[view.mode];
  if (view.mode === "oauth_password") {
    const tokenUrl = text(draft[SERVICENOW_OIDC_FIELDS.tokenUrl]);
    if (tokenUrl) body[SERVICENOW_OIDC_FIELDS.tokenUrl] = tokenUrl;
    const scope = text(draft[SERVICENOW_OIDC_FIELDS.scope]);
    if (scope) body[SERVICENOW_OIDC_FIELDS.scope] = scope;
    else if (text(connector.public_fields?.[SERVICENOW_OIDC_FIELDS.scope])) body[SERVICENOW_OIDC_FIELDS.scope] = "";
  }
  for (const principal of spec.principals) if (text(draft[principal.field])) body[principal.field] = text(draft[principal.field]);
  for (const secret of spec.secrets) if (text(draft[secret.field])) body[secret.field] = text(draft[secret.field]);
  return body;
}

/** One line about what is saved; never claims the credentials work. */
// A field label inside a sentence: only its first letter lower case ("token endpoint URL", not "token endpoint url").
const inSentence = (label: string) => label.charAt(0).toLowerCase() + label.slice(1);

export function storedServiceNowSummary(connector: AdminConnector): string {
  const stored = storedServiceNowMode(connector);
  if (stored === "none") return "No sign-in method is saved yet.";
  if (stored === "unknown") return "The saved sign-in method is not recognised.";
  const spec = MODES[stored];
  const missing = [
    usesTokenUrl(stored) && !text(connector.public_fields?.[SERVICENOW_OIDC_FIELDS.tokenUrl]) && inSentence(OIDC_TEXT.tokenUrlLabel),
    ...spec.principals.map((principal) => !text(connector.public_fields?.[principal.field]) && inSentence(principal.label)),
    ...spec.secrets.map((secret) => !connector.secret_status?.[secret.field] && inSentence(secret.label)),
  ].filter(Boolean);
  // That a save does not verify the sign-in is in the Connector settings help.
  return missing.length
    ? `Saved: ${spec.label}, incomplete (missing ${missing.join(" and ")}).`
    : `Saved: ${spec.label}.`;
}
