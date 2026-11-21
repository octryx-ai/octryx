import type { ConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";
import { CredentialInput, FieldError } from "./ConnectorCredentialInput";
import { CLIENT_AUTH_LABEL, CLIENT_AUTH_METHODS, OIDC_TEXT } from "./oidcClientCredentialsModel";
import type { OidcFieldError, OidcFieldNames } from "./oidcClientCredentialsModel";

type Shared = {
  names: OidcFieldNames;
  draft: Record<string, string>;
  set: (field: string, value: string) => void;
  shown: (field: string) => OidcFieldError | null;
  id: (field: string) => string;
  rebind: Pick<ConnectorSecretRebind, "flow">;
};

// The OpenID Connect client-credentials fields, shared by Confluence, Jira (global and Workspace own
// connection) and ServiceNow. Placeholders are neutral or empty: no real host, realm, tenant or client id.

/** The token endpoint, shown before the client id and secret. */
export function OidcTokenUrlField({ names, draft, set, shown, id, rebind }: Shared) {
  return (
    <CredentialInput
      field={names.tokenUrl}
      label={OIDC_TEXT.tokenUrlLabel}
      type="url"
      value={draft[names.tokenUrl] ?? ""}
      placeholder="https://"
      help={OIDC_TEXT.tokenUrlHelp}
      error={shown(names.tokenUrl)}
      id={id}
      rebind={rebind}
      onChange={set}
    />
  );
}

/** Scope and audience (optional), then the client authentication method under "Advanced". */
export function OidcOptionalFields({ names, draft, set, shown, id, rebind }: Shared) {
  const clientAuth = draft[names.clientAuth] ?? "";
  return (
    <>
      <CredentialInput field={names.scope} label={OIDC_TEXT.scopeLabel} type="text" value={draft[names.scope] ?? ""}
        placeholder="" help={OIDC_TEXT.scopeHelp} error={shown(names.scope)} id={id} rebind={rebind} onChange={set} />
      <CredentialInput field={names.audience} label={OIDC_TEXT.audienceLabel} type="text" value={draft[names.audience] ?? ""}
        placeholder="" help={OIDC_TEXT.audienceHelp} error={shown(names.audience)} id={id} rebind={rebind} onChange={set} />
      <details className="connector-field" open={Boolean(clientAuth) && clientAuth !== CLIENT_AUTH_METHODS[0]}>
        <summary className="connector-field__label">Advanced</summary>
        <label className="connector-field__label" htmlFor={id(names.clientAuth)}>{OIDC_TEXT.clientAuthLabel}</label>
        <select id={id(names.clientAuth)} className="connector-field__input" value={clientAuth}
          onChange={(event) => set(names.clientAuth, event.target.value)}>
          <option value="">Default (client id and secret in the request body)</option>
          {CLIENT_AUTH_METHODS.map((method) => <option key={method} value={method}>{CLIENT_AUTH_LABEL[method]}</option>)}
        </select>
        <FieldError error={shown(names.clientAuth)} />
      </details>
    </>
  );
}
