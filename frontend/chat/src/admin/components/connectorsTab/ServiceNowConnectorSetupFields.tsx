import type { ConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";
import { connectorFieldInputId } from "../../secretRebind/useConnectorSecretRebind";
import { ConfiguredConnectorFieldsPanel } from "./ConfiguredConnectorFieldsPanel";
import { CredentialInput, FieldError, Option } from "./ConnectorCredentialInput";
import { OIDC_TEXT, SERVICENOW_OIDC_FIELDS } from "./oidcClientCredentialsModel";
import type { OidcFieldError } from "./oidcClientCredentialsModel";
import { OidcOptionalFields, OidcTokenUrlField } from "./OidcClientCredentialsFields";
import { ServiceNowApiFields } from "./ServiceNowApiFields";
import { ServiceNowAssignmentGroupsField } from "./ServiceNowAssignmentGroupsField";
import { serviceNowApiOwnedFields } from "./serviceNowApiModel";
import type { ServiceNowSetupView } from "./serviceNowApiModel";
import { LIMIT_FIELDS } from "./serviceNowGroupsModel";
import {
  SERVICENOW_AUTH_MODES,
  SERVICENOW_AUTH_MODE_FIELD,
  SERVICENOW_URL_FIELD,
  defaultServiceNowTokenUrl,
  serviceNowModeFields,
  serviceNowOwnedFields,
  storedServiceNowSummary,
} from "./serviceNowAuthModel";
import type { ServiceNowAuthMode } from "./serviceNowAuthModel";
import { ConnectorFieldGroup } from "./ConnectorFieldGroup";
import { GROUP_TITLES } from "./connectorFieldGroupsModel";
import "./jiraConnectorSetup.css";

type ServiceNowConnectorSetupFieldsProps = {
  connector: any;
  draft: Record<string, string>;
  view: ServiceNowSetupView;
  ctx: Record<string, unknown>;
  rebind: ConnectorSecretRebind;
  showAllErrors: boolean;
};

const TOKEN_URL = SERVICENOW_OIDC_FIELDS.tokenUrl;

type SetupHandlerInput = ServiceNowConnectorSetupFieldsProps;
type Shown = (field: string) => OidcFieldError | null;

/** Field edits (each also tells the secret rebind), input ids, the errors to show, the URL and the method choice. */
function serviceNowSetupHandlers({ connector, draft, view, ctx, rebind, showAllErrors }: SetupHandlerInput) {
  const { setConnectorField } = ctx as Record<string, any>;
  const toolName: string = connector.tool_name;
  const auth = view.auth;
  const set = (field: string, value: string) => {
    setConnectorField(toolName, field, value);
    rebind.fieldEdited(field);
  };
  const id = (field: string) => connectorFieldInputId(toolName, field);
  const shown = (field: string) => {
    const error = view.errors[field];
    return error && (error.live || showAllErrors) ? error : null;
  };
  // The password grant's token URL follows the instance URL while it is empty or still the prefill.
  const setUrl = (value: string) => {
    const tokenUrl = (draft[TOKEN_URL] ?? "").trim();
    if (auth.mode === "oauth_password" && (!tokenUrl || tokenUrl === defaultServiceNowTokenUrl(draft[SERVICENOW_URL_FIELD] ?? ""))) {
      set(TOKEN_URL, defaultServiceNowTokenUrl(value) ?? "");
    }
    set(SERVICENOW_URL_FIELD, value);
  };
  // A typed secret belongs to the method it was typed for: changing the method clears it.
  const choose = (next: ServiceNowAuthMode | "") => {
    if (auth.mode && auth.mode !== next) {
      for (const secret of serviceNowModeFields(auth.mode).secrets) if ((draft[secret.field] ?? "") !== "") set(secret.field, "");
    }
    if (next === "oauth_password" && !(draft[TOKEN_URL] ?? "").trim()) {
      const prefill = defaultServiceNowTokenUrl(draft[SERVICENOW_URL_FIELD] ?? "");
      if (prefill) set(TOKEN_URL, prefill);
    }
    set(SERVICENOW_AUTH_MODE_FIELD, next);
  };
  return { set, id, shown, setUrl, choose };
}

/** How ServiceNow signs in: one option per method. */
function ServiceNowMethodChoice({ connector, auth, id, shown, choose }: {
  connector: any;
  auth: ServiceNowSetupView["auth"];
  id: (field: string) => string;
  shown: Shown;
  choose: (next: ServiceNowAuthMode | "") => void;
}) {
  return (
    <div className="connector-field jira-setup__group" role="radiogroup" aria-labelledby={`${id(SERVICENOW_AUTH_MODE_FIELD)}-label`}>
      <span id={`${id(SERVICENOW_AUTH_MODE_FIELD)}-label`} className="connector-field__label">How ServiceNow signs in</span>
      <span className="admin-panel__hint">{storedServiceNowSummary(connector)}</span>
      <div className="jira-setup__options">
        {SERVICENOW_AUTH_MODES.map((mode) => (
          <Option key={mode} name={id(SERVICENOW_AUTH_MODE_FIELD)} value={mode} checked={auth.mode === mode}
            onChoose={() => choose(mode)} title={serviceNowModeFields(mode).label} help={serviceNowModeFields(mode).help} />
        ))}
      </div>
      <FieldError error={shown(SERVICENOW_AUTH_MODE_FIELD)} />
    </div>
  );
}

/** The chosen method's fields: token URL, principals, secrets (kept when stored) and the optional scope settings. */
function ServiceNowSignInFields({ auth, fields, oidc, draft, set, shown, id, rebind }: {
  auth: ServiceNowSetupView["auth"];
  fields: ReturnType<typeof serviceNowModeFields>;
  oidc: { names: typeof SERVICENOW_OIDC_FIELDS; draft: Record<string, string>; set: (field: string, value: string) => void;
    shown: Shown; id: (field: string) => string; rebind: ConnectorSecretRebind } | null;
  draft: Record<string, string>;
  set: (field: string, value: string) => void;
  shown: Shown;
  id: (field: string) => string;
  rebind: ConnectorSecretRebind;
}) {
  return (
  <>
    {auth.switching ? (
      <span className="security-field-hint security-field-hint--attention" role="note">
        The sign-in method changes: enter its secrets again. Only the chosen method&apos;s credentials are used
        after saving.
      </span>
    ) : null}
    {oidc ? <OidcTokenUrlField {...oidc} /> : null}
    {auth.mode === "oauth_password" ? (
      <CredentialInput field={TOKEN_URL} label="Token URL" type="url" value={draft[TOKEN_URL] ?? ""} placeholder="https://"
        help="The instance's OAuth token endpoint; prefilled from the ServiceNow URL, change it if yours differs."
        error={shown(TOKEN_URL)} id={id} rebind={rebind} onChange={set} />
    ) : null}
    {fields.principals.map((principal) => (
      <CredentialInput key={principal.field} field={principal.field} label={principal.label} type="text"
        value={draft[principal.field] ?? ""} placeholder="" error={shown(principal.field)} id={id} rebind={rebind} onChange={set} />
    ))}
    {fields.secrets.map((secret) => (
      <CredentialInput key={secret.field} field={secret.field} label={secret.label} type="password" secret
        value={draft[secret.field] ?? ""}
        placeholder={auth.keepable[secret.field] ? "••••••• (stored — leave blank to keep)" : `Enter the ${secret.label.toLowerCase()}`}
        error={shown(secret.field)} id={id} rebind={rebind} onChange={set} />
    ))}
    {oidc ? <OidcOptionalFields {...oidc} /> : null}
    {auth.mode === "oauth_password" ? (
      <CredentialInput field={SERVICENOW_OIDC_FIELDS.scope} label={OIDC_TEXT.scopeLabel} type="text"
        value={draft[SERVICENOW_OIDC_FIELDS.scope] ?? ""} placeholder="" help={OIDC_TEXT.scopeHelp}
        error={shown(SERVICENOW_OIDC_FIELDS.scope)} id={id} rebind={rebind} onChange={set} />
    ) : null}
  </>
  );
}

// ServiceNow (extension): the instance URL, an explicit sign-in method with only its fields, the API
// section (Table or Scripted REST), the record limit (groups, services), then the remaining preset fields (allowed
// tables) in the generic panel. A connector without a saved method needs one chosen before it saves.
export function ServiceNowConnectorSetupFields({ connector, draft, view, ctx, rebind, showAllErrors }: ServiceNowConnectorSetupFieldsProps) {
  const auth = view.auth;
  const { set, id, shown, setUrl, choose } = serviceNowSetupHandlers({ connector, draft, view, ctx, rebind, showAllErrors });
  const fields = auth.mode ? serviceNowModeFields(auth.mode) : null;
  const oidc = auth.mode === "oidc_client_credentials" ? { names: SERVICENOW_OIDC_FIELDS, draft, set, shown, id, rebind } : null;
  const owned = new Set([...serviceNowOwnedFields(), ...serviceNowApiOwnedFields(), ...LIMIT_FIELDS]);
  const rest = { ...connector, fields: (connector.fields || []).filter((field: string) => !owned.has(field)) };

  return (
    <>
      <div data-testid="servicenow-auth">
      <ConnectorFieldGroup group="connection" title={GROUP_TITLES.connection}>
      <div className="connector-card__fields">
        <CredentialInput field={SERVICENOW_URL_FIELD} label="ServiceNow URL" type="url" value={draft[SERVICENOW_URL_FIELD] ?? ""}
          placeholder="https://" help="The base URL of your ServiceNow instance." error={shown(SERVICENOW_URL_FIELD)}
          id={id} rebind={rebind} onChange={(_field, value) => setUrl(value)} />
        <ServiceNowApiFields view={view.api} draft={draft} set={set} shown={shown} id={id} rebind={rebind} />
      </div>
      </ConnectorFieldGroup>
      <ConnectorFieldGroup group="authentication" title={GROUP_TITLES.authentication}>
      <div className="connector-card__fields">
        <ServiceNowMethodChoice connector={connector} auth={auth} id={id} shown={shown} choose={choose} />
        {fields && auth.mode ? (
          <ServiceNowSignInFields auth={auth} fields={fields} oidc={oidc} draft={draft} set={set} shown={shown} id={id}
            rebind={rebind} />
        ) : null}
      </div>
      </ConnectorFieldGroup>
      <ConnectorFieldGroup group="scope" title={GROUP_TITLES.scope}>
        <div className="connector-card__fields">
          <ServiceNowAssignmentGroupsField connector={connector} draft={draft} set={set} id={id} />
        </div>
        {rest.fields.length ? (
          <ConfiguredConnectorFieldsPanel connector={rest} draft={draft} ctx={ctx} rebind={rebind} grouped={false} />
        ) : null}
      </ConnectorFieldGroup>
      </div>
    </>
  );
}
