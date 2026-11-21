import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import {
  OIDC_TEXT,
  atlassianOidcFields,
  oidcSaveFields,
} from "./oidcClientCredentialsModel";
import {
  authModeField,
  authModeFields,
  authUrlField,
  storedAuthMode,
  text,
  type AtlassianProduct,
} from "./atlassianAuthModes";
import { atlassianAuthView } from "./atlassianAuthView";

/**
 * The sign-in part of the save body: the URL and, for an explicit method, the method with its principal
 * and a typed secret. Never sends another method's fields.
 */
export function atlassianAuthSaveFields(
  product: AtlassianProduct,
  connector: AdminConnector,
  draft: Record<string, string>,
): Record<string, unknown> {
  const view = atlassianAuthView(product, connector, draft);
  const body: Record<string, unknown> = {};
  const url = text(draft[authUrlField(product)]);
  if (url) body[authUrlField(product)] = url;
  if (view.mode) {
    const fields = authModeFields(product, view.mode);
    body[authModeField(product)] = view.mode;
    if (fields.principal) {
      const principal = text(draft[fields.principal]);
      if (principal) body[fields.principal] = principal;
    }
    const secret = text(draft[fields.secret]);
    if (secret) body[fields.secret] = secret;
    if (view.mode === "oidc_client_credentials") {
      Object.assign(body, oidcSaveFields(atlassianOidcFields(product), draft, connector.public_fields));
    }
  }
  return body;
}

/** One line about what is saved; never claims the credentials work. */
// A field label inside a sentence: only its first letter lower case ("token endpoint URL", not "token endpoint url").
const inSentence = (label: string) => label.charAt(0).toLowerCase() + label.slice(1);

export function storedAuthSummary(
  product: AtlassianProduct,
  connector: AdminConnector,
): string {
  const stored = storedAuthMode(product, connector);
  if (stored === "none") return "No sign-in method is saved yet.";
  if (stored === "unknown")
    return "The saved sign-in method is not recognised.";
  const fields = authModeFields(product, stored);
  const tokenUrl = atlassianOidcFields(product).tokenUrl;
  const missing = [
    stored === "oidc_client_credentials" &&
      !text(connector.public_fields?.[tokenUrl]) &&
      inSentence(OIDC_TEXT.tokenUrlLabel),
    fields.principal &&
      !text(connector.public_fields?.[fields.principal]) &&
      inSentence(fields.principalLabel),
    !connector.secret_status?.[fields.secret] &&
      inSentence(fields.secretLabel),
  ].filter(Boolean);
  const where =
    stored === "cloud_api_token"
      ? "Atlassian Cloud"
      : `Own instance · ${fields.label}`;
  // The method as it is named in the form ("OpenID Connect (client credentials)"); that a save
  // does not verify the sign-in is in the Connector settings help.
  return missing.length
    ? `Saved: ${where}, incomplete (missing ${missing.join(" and ")}).`
    : `Saved: ${where}.`;
}
