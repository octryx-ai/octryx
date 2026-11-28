// Every value is entered by the admin: nothing here names a host, realm, tenant or client id.

export type OidcFieldNames = {
  tokenUrl: string;
  clientId: string;
  clientSecret: string;
  scope: string;
  audience: string;
  clientAuth: string;
};

export const OIDC_MODE = "oidc_client_credentials";

export const CLIENT_AUTH_METHODS = ["client_secret_post", "client_secret_basic"] as const;
export type ClientAuthMethod = (typeof CLIENT_AUTH_METHODS)[number];

export const CLIENT_AUTH_LABEL: Record<ClientAuthMethod, string> = {
  client_secret_post: "Client id and secret in the request body (default)",
  client_secret_basic: "Client id and secret as HTTP Basic authentication",
};

export const OIDC_TEXT = {
  label: "OpenID Connect (client credentials)",
  help: "A technical client registered in your identity provider: its token endpoint, client id and client secret. The connector requests short-lived access tokens itself.",
  tokenUrlLabel: "Token endpoint URL",
  tokenUrlHelp: "Token endpoint of your identity provider (OpenID Connect).",
  clientIdLabel: "Client id",
  clientSecretLabel: "Client secret",
  scopeLabel: "Scope (optional)",
  scopeHelp: "Only when your identity provider requires one; sent as entered.",
  audienceLabel: "Audience (optional)",
  audienceHelp: "Only when your identity provider requires one; sent as entered.",
  clientAuthLabel: "Client authentication (advanced)",
} as const;

export function atlassianOidcFields(product: string): OidcFieldNames {
  return {
    tokenUrl: `${product}_oidc_token_url`,
    clientId: `${product}_oidc_client_id`,
    clientSecret: `${product}_oidc_client_secret`,
    scope: `${product}_oidc_scope`,
    audience: `${product}_oidc_audience`,
    clientAuth: `${product}_oidc_client_auth`,
  };
}

export const SERVICENOW_OIDC_FIELDS: OidcFieldNames = {
  tokenUrl: "servicenow_token_url",
  clientId: "servicenow_client_id",
  clientSecret: "servicenow_client_secret",
  scope: "servicenow_oauth_scope",
  audience: "servicenow_oidc_audience",
  clientAuth: "servicenow_oidc_client_auth",
};

export function oidcSettingFields(names: OidcFieldNames): string[] {
  return [names.tokenUrl, names.scope, names.audience, names.clientAuth];
}

const LOOPBACK = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

/** Plain http is accepted only on a loopback host, for local test endpoints. */
export function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK.has(hostname.toLowerCase());
}

export function tokenUrlProblem(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return "Enter the full token endpoint URL, starting with https://.";
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return "The token endpoint URL must start with https://.";
  if (!url.hostname) return "The token endpoint URL needs a host name.";
  if (url.username || url.password) return "Remove the user name or password from the token endpoint URL; the client id and secret have their own fields.";
  if (url.protocol === "http:" && !isLoopbackHost(url.hostname)) {
    return "The token endpoint must use https://; http is accepted only for a local test endpoint.";
  }
  if (url.hash) return "Remove the fragment (#…) from the token endpoint URL.";
  return null;
}

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

export type OidcFieldError = { message: string; live: boolean };

export function oidcSettingErrors(names: OidcFieldNames, draft: Record<string, string>): Record<string, OidcFieldError> {
  const errors: Record<string, OidcFieldError> = {};
  const tokenUrl = text(draft[names.tokenUrl]);
  if (!tokenUrl) errors[names.tokenUrl] = { message: "Enter the token endpoint URL.", live: false };
  else {
    const problem = tokenUrlProblem(tokenUrl);
    if (problem) errors[names.tokenUrl] = { message: problem, live: true };
  }
  const clientAuth = text(draft[names.clientAuth]);
  if (clientAuth && !(CLIENT_AUTH_METHODS as readonly string[]).includes(clientAuth)) {
    errors[names.clientAuth] = { message: "Choose how the client authenticates at the token endpoint.", live: true };
  }
  return errors;
}

/** A stored optional field that is cleared is sent as "", so a removed scope or audience is not kept silently. */
export function oidcSaveFields(
  names: OidcFieldNames,
  draft: Record<string, string>,
  stored: Record<string, unknown> | undefined,
): Record<string, string> {
  const body: Record<string, string> = {};
  for (const field of [names.tokenUrl, names.clientId]) {
    const value = text(draft[field]);
    if (value) body[field] = value;
  }
  for (const field of [names.scope, names.audience, names.clientAuth]) {
    const value = text(draft[field]);
    if (value) body[field] = value;
    else if (text(stored?.[field])) body[field] = "";
  }
  const secret = text(draft[names.clientSecret]);
  if (secret) body[names.clientSecret] = secret;
  return body;
}

const TEST_CODE_HINTS: Record<string, string> = {
  oidc_token_endpoint_unreachable:
    "The token endpoint could not be reached. Check the token endpoint URL and that the egress policy allows its host.",
  oidc_token_endpoint_redirect:
    "The token endpoint answered with a redirect. Enter the final token endpoint URL; the client secret is never sent to a redirect target.",
  oidc_invalid_client:
    "The identity provider refused the client. Check the client id, the client secret and the client authentication method.",
  oidc_unauthorized_client:
    "The identity provider does not allow this client to use client credentials. Enable the client credentials grant for it in the identity provider.",
  oidc_token_url_invalid:
    "The token endpoint URL cannot be used. Enter the full https URL of the token endpoint, without user name, password or fragment.",
  oidc_bad_response:
    "The token endpoint answered without an access token. Check that the URL is the token endpoint of your identity provider.",
  // ServiceNow's own OAuth with the password grant.
  oauth_invalid_client:
    "ServiceNow refused the OAuth client. Check the client id and the client secret of the OAuth application.",
  oauth_invalid_grant:
    "ServiceNow refused the username or password of the integration user. Check both; the account may also be locked.",
  oauth_unauthorized_client:
    "The OAuth client may not use the password grant. Allow it for the OAuth application in ServiceNow.",
  oauth_token_endpoint_redirect:
    "The token URL answered with a redirect. Enter the final token URL; credentials are never sent to a redirect target.",
  oauth_bad_response:
    "The token URL answered without an access token. Check that it is the instance's OAuth token endpoint.",
  connector_unauthorized:
    "The identity provider issued a token, but the target system refused it. The technical user may lack access in the target system.",
};

export function testCodeHint(code: unknown): string | null {
  return typeof code === "string" ? TEST_CODE_HINTS[code] ?? null : null;
}

export function testResultHint(result: unknown): string | null {
  if (!result || typeof result !== "object") return null;
  const record = result as Record<string, unknown>;
  const hint = testCodeHint(record.auth_code);
  if (!hint) return null;
  return typeof record.summary === "string" && record.summary.includes(hint) ? null : hint;
}
