// Atlassian sign-in methods, their fields per product and the saved method of a connector.
import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import {
  OIDC_TEXT,
  atlassianOidcFields,
  oidcSettingFields,
} from "./oidcClientCredentialsModel";

export type AtlassianProduct = "confluence" | "jira";
export type AtlassianAuthMode = "cloud_api_token" | "basic" | "bearer_pat" | "oidc_client_credentials";
export type AtlassianLocation = "cloud" | "own";
export type StoredAuthMode = AtlassianAuthMode | "none" | "unknown";

export const AUTH_MODES: readonly AtlassianAuthMode[] = [
  "cloud_api_token",
  "basic",
  "bearer_pat",
  "oidc_client_credentials",
];

/** The own-instance methods, in the order the form offers them. */
export const OWN_INSTANCE_MODES: readonly AtlassianAuthMode[] = ["basic", "bearer_pat", "oidc_client_credentials"];

export type AuthModeFields = {
  principal: string | null;
  secret: string;
  principalLabel: string;
  secretLabel: string;
  label: string;
  help: string;
};

export const PRODUCT_LABEL: Record<AtlassianProduct, string> = {
  confluence: "Confluence",
  jira: "Jira",
};

const MODE_FIELDS: Record<
  AtlassianProduct,
  Record<AtlassianAuthMode, { principal: string | null; secret: string }>
> = {
  confluence: {
    cloud_api_token: {
      principal: "confluence_username",
      secret: "confluence_token",
    },
    basic: { principal: "confluence_username", secret: "confluence_password" },
    bearer_pat: { principal: null, secret: "confluence_token" },
    oidc_client_credentials: { principal: "confluence_oidc_client_id", secret: "confluence_oidc_client_secret" },
  },
  jira: {
    cloud_api_token: { principal: "jira_email", secret: "jira_token" },
    basic: { principal: "jira_username", secret: "jira_password" },
    bearer_pat: { principal: null, secret: "jira_token" },
    oidc_client_credentials: { principal: "jira_oidc_client_id", secret: "jira_oidc_client_secret" },
  },
};

export function authModeField(product: AtlassianProduct): string {
  return `${product}_auth_mode`;
}

export function authUrlField(product: AtlassianProduct): string {
  return `${product}_url`;
}

/** UI-only draft key for "own instance" chosen before its sign-in method. Never sent. */
export function authLocationDraftKey(product: AtlassianProduct): string {
  return `__${product}_auth_location`;
}

export function authModeFields(
  product: AtlassianProduct,
  mode: AtlassianAuthMode,
): AuthModeFields {
  const fields = MODE_FIELDS[product][mode];
  const name = PRODUCT_LABEL[product];
  if (mode === "cloud_api_token") {
    return {
      ...fields,
      principalLabel: "Atlassian account email",
      secretLabel: "API token",
      label: "Atlassian Cloud",
      help: `The email of the Atlassian account and an API token created at id.atlassian.com (Security, API tokens).${
        product === "confluence" ? " The Confluence URL ends with /wiki." : ""
      }`,
    };
  }
  if (mode === "basic") {
    return {
      ...fields,
      principalLabel: "Username",
      secretLabel: "Password",
      label: "Username and password",
      help: `A ${name} account's username and password. Some installations turn basic sign-in off; then use a personal access token.`,
    };
  }
  if (mode === "oidc_client_credentials") {
    return {
      ...fields,
      principalLabel: OIDC_TEXT.clientIdLabel,
      secretLabel: OIDC_TEXT.clientSecretLabel,
      label: OIDC_TEXT.label,
      help: OIDC_TEXT.help,
    };
  }
  return {
    ...fields,
    principalLabel: "",
    secretLabel: "Personal access token",
    label: "Personal access token",
    help: `A personal access token created in the ${name} profile (Personal access tokens). No username is needed.`,
  };
}

/** Every field the guided sign-in owns, so the generic panel and save loop leave them alone. */
export function authOwnedFields(product: AtlassianProduct): string[] {
  const fields = new Set<string>([
    authUrlField(product),
    authModeField(product),
  ]);
  for (const mode of AUTH_MODES) {
    const { principal, secret } = MODE_FIELDS[product][mode];
    if (principal) fields.add(principal);
    fields.add(secret);
  }
  for (const field of oidcSettingFields(atlassianOidcFields(product))) fields.add(field);
  return Array.from(fields);
}

export function locationOf(mode: AtlassianAuthMode): AtlassianLocation {
  return mode === "cloud_api_token" ? "cloud" : "own";
}

export function isMode(value: unknown): value is AtlassianAuthMode {
  return (
    typeof value === "string" &&
    (AUTH_MODES as readonly string[]).includes(value)
  );
}

export function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** The saved sign-in method: none when absent, unknown for a non-contract value. */
export function storedAuthMode(
  product: AtlassianProduct,
  connector: AdminConnector,
): StoredAuthMode {
  const raw = connector.public_fields?.[authModeField(product)];
  if (isMode(raw)) return raw;
  return raw !== undefined && raw !== null && raw !== "" ? "unknown" : "none";
}
