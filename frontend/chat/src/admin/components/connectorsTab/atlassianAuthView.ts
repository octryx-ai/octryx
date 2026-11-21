// Validation view of the Atlassian sign-in form: URL problems, chosen method, field errors.
import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import { atlassianOidcFields, oidcSettingErrors } from "./oidcClientCredentialsModel";
import {
  PRODUCT_LABEL,
  authLocationDraftKey,
  authModeField,
  authModeFields,
  authUrlField,
  isMode,
  locationOf,
  storedAuthMode,
  text,
  type AtlassianAuthMode,
  type AtlassianLocation,
  type AtlassianProduct,
  type StoredAuthMode,
} from "./atlassianAuthModes";

export type AuthFieldError = { message: string; live: boolean };

export type AtlassianAuthView = {
  product: AtlassianProduct;
  stored: StoredAuthMode;
  /** The chosen explicit method, or null (nothing chosen yet, or own instance without a method). */
  mode: AtlassianAuthMode | null;
  location: AtlassianLocation | null;
  /** The chosen method differs from the saved explicit (or unrecognised) one. */
  switching: boolean;
  /** Leaving the secret blank keeps the stored one. */
  secretKeepable: boolean;
  urlNote: string | null;
  /** The URL is Atlassian Cloud but Cloud is not chosen. */
  cloudSuggested: boolean;
  errors: Record<string, AuthFieldError>;
};

export function atlassianUrlProblem(
  product: AtlassianProduct,
  value: string,
): string | null {
  const name = PRODUCT_LABEL[product];
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return `Enter a full URL such as https://your-site.atlassian.net${product === "confluence" ? "/wiki" : ""}.`;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return `The ${name} URL must start with https:// (or http:// for an http-only installation).`;
  }
  if (url.username || url.password)
    return "Remove the user name or password from the URL; enter credentials in the fields below.";
  if (!url.hostname) return `The ${name} URL needs a host name.`;
  if (url.search || url.hash)
    return `Remove the query string or fragment from the ${name} URL.`;
  return null;
}

function isCloudHost(value: string): boolean {
  try {
    return new URL(value).hostname.toLowerCase().endsWith(".atlassian.net");
  } catch {
    return false;
  }
}

function chosenMode(
  product: AtlassianProduct,
  draft: Record<string, string>,
): AtlassianAuthMode | null {
  const value = text(draft[authModeField(product)]);
  return isMode(value) ? value : null;
}

type AuthErrors = Record<string, AuthFieldError>;

/** Adds the base URL's error to `errors` and returns the URL's note (plain http). */
function urlCheck(
  product: AtlassianProduct,
  mode: AtlassianAuthMode | null,
  url: string,
  errors: AuthErrors,
): string | null {
  const urlField = authUrlField(product);
  let urlNote: string | null = null;
  if (!url) {
    errors[urlField] = {
      message: `Enter the ${PRODUCT_LABEL[product]} base URL.`,
      live: false,
    };
  } else {
    const problem = atlassianUrlProblem(product, url);
    if (problem) errors[urlField] = { message: problem, live: true };
    else {
      if (url.toLowerCase().startsWith("http://")) {
        urlNote =
          "http sends the credentials unencrypted. Use https unless this installation only serves http; the egress policy decides which hosts are reachable.";
      }
      if (
        product === "confluence" &&
        mode === "cloud_api_token" &&
        isCloudHost(url)
      ) {
        const path = new URL(url).pathname.replace(/\/+$/, "");
        if (!path.endsWith("/wiki")) {
          errors[urlField] = {
            message:
              "A Confluence Cloud URL ends with /wiki, for example https://your-site.atlassian.net/wiki.",
            live: true,
          };
        }
      }
    }
  }
  return urlNote;
}

/** Adds the sign-in method's error when no method is chosen. */
function missingModeError(
  product: AtlassianProduct,
  stored: StoredAuthMode,
  location: AtlassianLocation | null,
  errors: AuthErrors,
): void {
  const modeField = authModeField(product);
  if (location === "own") {
    errors[modeField] = {
      message: "Choose how your own instance signs in.",
      live: false,
    };
  } else if (stored === "unknown") {
    errors[modeField] = {
      message:
        "The saved sign-in method is not recognised. Choose one before saving.",
      live: true,
    };
  } else {
    errors[modeField] = {
      message: `Choose how ${PRODUCT_LABEL[product]} signs in.`,
      live: false,
    };
  }
}

/** Adds the chosen method's field errors and returns whether a blank secret keeps the stored one. */
function modeFieldErrors(
  product: AtlassianProduct,
  connector: AdminConnector,
  draft: Record<string, string>,
  mode: AtlassianAuthMode,
  switching: boolean,
  errors: AuthErrors,
): boolean {
  const fields = authModeFields(product, mode);
  if (mode === "oidc_client_credentials") {
    Object.assign(errors, oidcSettingErrors(atlassianOidcFields(product), draft));
  }
  if (fields.principal) {
    const principal = text(draft[fields.principal]);
    if (!principal) {
      errors[fields.principal] = {
        message: `Enter the ${fields.principalLabel.toLowerCase()}.`,
        live: false,
      };
    } else if (mode === "cloud_api_token" && !principal.includes("@")) {
      errors[fields.principal] = {
        message:
          "Atlassian Cloud signs in with the Atlassian account email address.",
        live: true,
      };
    }
  }
  const secretKeepable = Boolean(connector.secret_status?.[fields.secret]) && !switching;
  if (!text(draft[fields.secret]) && !secretKeepable) {
    errors[fields.secret] = {
      // "new" only where a stored secret exists but is not reused.
      message:
        switching
          ? `Enter a new ${fields.secretLabel.toLowerCase()}: the sign-in method changes, so the stored secret is not reused.`
          : `Enter the ${fields.secretLabel.toLowerCase()}.`,
      live: false,
    };
  }
  return secretKeepable;
}

export function atlassianAuthView(
  product: AtlassianProduct,
  connector: AdminConnector,
  draft: Record<string, string>,
): AtlassianAuthView {
  const stored = storedAuthMode(product, connector);
  const mode = chosenMode(product, draft);
  const draftLocation = text(draft[authLocationDraftKey(product)]);
  const location: AtlassianLocation | null = mode
    ? locationOf(mode)
    : draftLocation === "cloud" || draftLocation === "own"
      ? draftLocation
      : null;
  const switching =
    Boolean(mode) &&
    (stored === "unknown" || (isMode(stored) && stored !== mode));
  const errors: AuthErrors = {};

  const url = text(draft[authUrlField(product)]);
  const urlNote = urlCheck(product, mode, url, errors);
  const cloudSuggested =
    Boolean(url) && isCloudHost(url) && location !== "cloud";

  let secretKeepable = false;
  if (!mode) missingModeError(product, stored, location, errors);
  else secretKeepable = modeFieldErrors(product, connector, draft, mode, switching, errors);

  return {
    product,
    stored,
    mode,
    location,
    switching,
    secretKeepable,
    urlNote,
    cloudSuggested,
    errors,
  };
}
