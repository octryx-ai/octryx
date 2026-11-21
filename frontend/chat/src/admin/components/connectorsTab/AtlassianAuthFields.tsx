import type { ConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";
import { connectorFieldInputId } from "../../secretRebind/useConnectorSecretRebind";
import { authLocationDraftKey, authModeField, authModeFields, authUrlField, locationOf } from "./atlassianAuthModes";
import { atlassianOidcFields } from "./oidcClientCredentialsModel";
import {
  AtlassianCredentialFields,
  AtlassianLocationGroup,
  AtlassianOwnMethodGroup,
  AtlassianUrlField,
  type AtlassianFieldContext,
} from "./AtlassianAuthFieldGroups";
import type { AtlassianAuthMode, AtlassianLocation, AtlassianProduct } from "./atlassianAuthModes";
import type { AtlassianAuthView, AuthFieldError } from "./atlassianAuthView";
import "./jiraConnectorSetup.css";


type AtlassianAuthFieldsProps = {
  product: AtlassianProduct;
  connector: any;
  draft: Record<string, string>;
  view: AtlassianAuthView;
  /** Sets one draft field and tells the secret-rebind flow it was edited. */
  set: (field: string, value: string) => void;
  // Only the secret-rebind flow is read; a form without that flow (Workspace connection) passes { flow: null }.
  rebind: Pick<ConnectorSecretRebind, "flow">;
  // After a save attempt every error shows; before, only errors about entered content.
  showAllErrors: boolean;
  // Delivery 5: the card shows the URL under Connection and the sign-in under Authentication.
  part?: "all" | "connection" | "authentication";
};

const PRODUCT_LABEL: Record<AtlassianProduct, string> = {
  confluence: "Confluence",
  jira: "Jira",
};

// A typed secret belongs to the method it was typed for. Cloud's API token
// and a personal access token share one field (*_token), so changing the method clears what was typed;
// an API token is never sent as a PAT, and the masked field never looks filled with the old value.
function atlassianAuthChoices(
  product: AtlassianProduct,
  draft: Record<string, string>,
  view: AtlassianAuthView,
  set: (field: string, value: string) => void,
) {
  const modeField = authModeField(product);
  const locationKey = authLocationDraftKey(product);
  const setMode = (next: AtlassianAuthMode | "") => {
    if (view.mode && view.mode !== next) {
      const typed = authModeFields(product, view.mode).secret;
      if ((draft[typed] ?? "") !== "") set(typed, "");
    }
    set(modeField, next);
  };
  const chooseLocation = (location: AtlassianLocation) => {
    if (location === "cloud") {
      set(locationKey, "cloud");
      setMode("cloud_api_token");
    } else {
      set(locationKey, "own");
      // Keep an own-instance method already chosen; leaving Cloud needs a new choice.
      if (!view.mode || locationOf(view.mode) !== "own") setMode("");
    }
  };
  const chooseMethod = (mode: AtlassianAuthMode) => {
    set(locationKey, "own");
    setMode(mode);
  };
  return { chooseLocation, chooseMethod };
}

// The URL and sign-in of a Confluence or Jira connector: where it runs (Atlassian Cloud or an
// own Server/Data Center instance), how an own instance signs in, and only that method's fields.
export function AtlassianAuthFields({
  product,
  connector,
  draft,
  view,
  set,
  rebind,
  showAllErrors,
  part = "all",
}: AtlassianAuthFieldsProps) {
  const toolName: string = connector.tool_name;
  const name = PRODUCT_LABEL[product];
  const id = (field: string) => connectorFieldInputId(toolName, field);
  const shown = (field: string): AuthFieldError | null => {
    const error = view.errors[field];
    return error && (error.live || showAllErrors) ? error : null;
  };
  const urlField = authUrlField(product);
  const modeField = authModeField(product);
  const locationKey = authLocationDraftKey(product);
  const { chooseLocation, chooseMethod } = atlassianAuthChoices(product, draft, view, set);
  const fc: AtlassianFieldContext = { product, name, draft, view, set, rebind, id, shown };
  // OpenID Connect adds the token endpoint before the client id and the optional settings after the secret.
  const oidc = view.mode === "oidc_client_credentials"
    ? { names: atlassianOidcFields(product), draft, set, shown, id, rebind }
    : null;

  return (
    <>
      {part !== "authentication" ? <AtlassianUrlField fc={fc} urlField={urlField} /> : null}

      {part !== "connection" ? (
      <>
      <AtlassianLocationGroup fc={fc} connector={connector} modeField={modeField} chooseLocation={chooseLocation} />

      {view.location === "own" ? (
        <AtlassianOwnMethodGroup fc={fc} modeField={modeField} locationKey={locationKey} chooseMethod={chooseMethod} />
      ) : null}

      {view.mode ? <AtlassianCredentialFields fc={fc} mode={view.mode} oidc={oidc} /> : null}
      </>
      ) : null}
    </>
  );
}
