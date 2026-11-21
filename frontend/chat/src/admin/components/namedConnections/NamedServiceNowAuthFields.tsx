import { CredentialInput, FieldError } from "../connectorsTab/ConnectorCredentialInput";
import {
  SERVICENOW_AUTH_MODES,
  SERVICENOW_AUTH_MODE_FIELD,
  SERVICENOW_URL_FIELD,
  serviceNowModeFields,
  usesTokenUrl,
} from "../connectorsTab/serviceNowAuthModel";
import { OIDC_TEXT, SERVICENOW_OIDC_FIELDS } from "../connectorsTab/oidcClientCredentialsModel";
import type { ServiceNowAuthView } from "../connectorsTab/serviceNowAuthModel";
import { connectorFieldInputId } from "../../secretRebind/useConnectorSecretRebind";

type Props = {
  toolName: string;
  draft: Record<string, string>;
  view: ServiceNowAuthView;
  set: (field: string, value: string) => void;
  showAllErrors: boolean;
};

const NO_REBIND = { flow: null };

// The sign-in of one ServiceNow named connection: instance URL, method, and only that method's fields.
// Validation and the save body come from the shared ServiceNow model, as on the global connector.
export function NamedServiceNowAuthFields({ toolName, draft, view, set, showAllErrors }: Props) {
  const id = (field: string) => connectorFieldInputId(toolName, field);
  const shown = (field: string) => {
    const error = view.errors[field];
    return error && (error.live || showAllErrors) ? error : null;
  };
  const spec = view.mode ? serviceNowModeFields(view.mode) : null;
  return (
    <>
      <CredentialInput
        field={SERVICENOW_URL_FIELD} label="ServiceNow URL" type="url" value={draft[SERVICENOW_URL_FIELD] ?? ""}
        placeholder="https://your-instance.service-now.com" error={shown(SERVICENOW_URL_FIELD)} id={id}
        rebind={NO_REBIND} onChange={set}
      />
      <div className="connector-field">
        <label className="connector-field__label" htmlFor={id(SERVICENOW_AUTH_MODE_FIELD)}>Sign-in method</label>
        <select
          id={id(SERVICENOW_AUTH_MODE_FIELD)}
          className="connector-field__input"
          value={draft[SERVICENOW_AUTH_MODE_FIELD] ?? ""}
          onChange={(event) => set(SERVICENOW_AUTH_MODE_FIELD, event.target.value)}
        >
          <option value="">Choose…</option>
          {SERVICENOW_AUTH_MODES.map((mode) => (
            <option key={mode} value={mode}>{serviceNowModeFields(mode).label}</option>
          ))}
        </select>
        <FieldError error={shown(SERVICENOW_AUTH_MODE_FIELD)} />
      </div>
      {spec && usesTokenUrl(view.mode) ? (
        <CredentialInput
          field={SERVICENOW_OIDC_FIELDS.tokenUrl} label={OIDC_TEXT.tokenUrlLabel} type="url"
          value={draft[SERVICENOW_OIDC_FIELDS.tokenUrl] ?? ""} placeholder="https://idp.example.com/oauth2/token"
          error={shown(SERVICENOW_OIDC_FIELDS.tokenUrl)} id={id} rebind={NO_REBIND} onChange={set}
        />
      ) : null}
      {spec?.principals.map((principal) => (
        <CredentialInput
          key={principal.field} field={principal.field} label={principal.label} type="text"
          value={draft[principal.field] ?? ""} placeholder="" error={shown(principal.field)} id={id}
          rebind={NO_REBIND} onChange={set}
        />
      ))}
      {spec?.secrets.map((secret) => (
        <CredentialInput
          key={secret.field} field={secret.field} label={secret.label} type="password" secret
          value={draft[secret.field] ?? ""}
          placeholder={view.keepable[secret.field] ? "Stored · leave empty to keep" : ""}
          error={shown(secret.field)} id={id} rebind={NO_REBIND} onChange={set}
        />
      ))}
    </>
  );
}
