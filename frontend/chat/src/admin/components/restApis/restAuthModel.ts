// REST API model: auth schemes and the definition and connection fields each scheme needs.
import type { AuthScheme, PublicField, SecretField } from "./restApisApi";

// ---- auth schemes ------------------------------------------------------------------------------------------------

export const AUTH_SCHEMES: ReadonlyArray<{ value: AuthScheme; label: string }> = [
  { value: "none", label: "No authentication" },
  { value: "api_key_header", label: "API key in a header" },
  { value: "api_key_query", label: "API key in the query" },
  { value: "bearer", label: "Bearer token" },
  { value: "basic", label: "User name and password (Basic)" },
  { value: "oauth2_client_credentials", label: "OAuth2 client credentials" },
];

export const schemeLabel = (scheme: string | undefined) =>
  AUTH_SCHEMES.find((entry) => entry.value === scheme)?.label ?? "No authentication";

export type DefinitionAuthField = "header_name" | "query_name" | "token_url" | "scopes";

/** The fields of the definition's auth block that a scheme needs (nothing else is shown or sent). */
export function definitionAuthFields(scheme: AuthScheme): DefinitionAuthField[] {
  if (scheme === "api_key_header") return ["header_name"];
  if (scheme === "api_key_query") return ["query_name"];
  if (scheme === "oauth2_client_credentials") return ["token_url", "scopes"];
  return [];
}

export type ConnectionField = { name: PublicField | SecretField; label: string; secret: boolean; required: boolean };

/** The fields a connection holds for the definition's scheme; secrets are write-only. */
export function connectionAuthFields(scheme: AuthScheme): ConnectionField[] {
  const secret = (name: SecretField, label: string): ConnectionField => ({ name, label, secret: true, required: true });
  const plain = (name: PublicField, label: string, required = false): ConnectionField => ({ name, label, secret: false, required });
  switch (scheme) {
    case "api_key_header":
    case "api_key_query":
      return [secret("api_key", "API key")];
    case "bearer":
      return [secret("token", "Token")];
    case "basic":
      return [plain("username", "User name", true), secret("password", "Password")];
    case "oauth2_client_credentials":
      return [
        plain("client_id", "Client ID", true), secret("client_secret", "Client secret"),
        plain("token_url", "Token URL (overrides the API's)"), plain("scope", "Scope"), plain("audience", "Audience"),
      ];
    default:
      return [];
  }
}
