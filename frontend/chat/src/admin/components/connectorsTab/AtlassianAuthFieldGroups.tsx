// The parts of the Atlassian URL and sign-in fields: the URL, where the product runs, how an own instance signs in,
// and the chosen method's credentials.
import { SecretRebindFieldHint } from "../../secretRebind/SecretRebindFieldHint";
import { CredentialInput, FieldError, Option } from "./ConnectorCredentialInput";
import { rebindFieldClass } from "../../secretRebind/secretRebindFlow";
import type { ConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";
import { OWN_INSTANCE_MODES, authModeFields } from "./atlassianAuthModes";
import { storedAuthSummary } from "./atlassianAuthModel";
import { OidcOptionalFields, OidcTokenUrlField } from "./OidcClientCredentialsFields";
import type { AtlassianAuthMode, AtlassianLocation, AtlassianProduct } from "./atlassianAuthModes";
import type { AtlassianAuthView, AuthFieldError } from "./atlassianAuthView";

/** What every part reads: the product, the draft, the derived view and the field helpers. */
export type AtlassianFieldContext = {
  product: AtlassianProduct;
  name: string;
  draft: Record<string, string>;
  view: AtlassianAuthView;
  set: (field: string, value: string) => void;
  rebind: Pick<ConnectorSecretRebind, "flow">;
  id: (field: string) => string;
  shown: (field: string) => AuthFieldError | null;
};

function errorClass(error: AuthFieldError | null): string {
  return error ? " security-field--error" : "";
}

export function AtlassianUrlField({ fc, urlField }: { fc: AtlassianFieldContext; urlField: string }) {
  const { product, name, draft, view, set, rebind, id, shown } = fc;
  return (
      <div className="connector-field">
        <label className="connector-field__label" htmlFor={id(urlField)}>
          {name} URL
        </label>
        <input
          id={id(urlField)}
          type="url"
          className={`connector-field__input${errorClass(shown(urlField))}${rebindFieldClass(rebind.flow, urlField)}`}
          value={draft[urlField] ?? ""}
          onChange={(event) => set(urlField, event.target.value)}
          placeholder={
            product === "confluence"
              ? "https://your-site.atlassian.net/wiki"
              : "https://your-site.atlassian.net"
          }
          aria-invalid={Boolean(shown(urlField))}
          aria-describedby={`${id(urlField)}-help`}
          autoComplete="off"
        />
        <span id={`${id(urlField)}-help`} className="ds-sr-only">
          {product === "confluence"
            ? "Cloud: https://your-site.atlassian.net/wiki. Server or Data Center: the base URL including any context path."
            : "Cloud: https://your-site.atlassian.net. Server or Data Center: the base URL including any context path."}
        </span>
        {view.urlNote ? (
          <span className="security-field-hint security-field-hint--attention">
            {view.urlNote}
          </span>
        ) : null}
        {view.cloudSuggested ? (
          <span
            className="security-field-hint security-field-hint--attention"
            data-testid={`${product}-cloud-suggestion`}
          >
            This address is Atlassian Cloud: choose Atlassian Cloud below.
          </span>
        ) : null}
        <FieldError error={shown(urlField)} />
        <SecretRebindFieldHint flow={rebind.flow} field={urlField} />
      </div>
  );
}

export function AtlassianLocationGroup({ fc, connector, modeField, chooseLocation }: {
  fc: AtlassianFieldContext;
  connector: any;
  modeField: string;
  chooseLocation: (location: AtlassianLocation) => void;
}) {
  const { product, name, view, id, shown } = fc;
  const locationValue = view.location;
  return (
      <div
        className="connector-field jira-setup__group"
        role="radiogroup"
        aria-labelledby={`${id(modeField)}-label`}
      >
        <span id={`${id(modeField)}-label`} className="connector-field__label">
          Where {name} runs
        </span>
        <span className="admin-panel__hint">
          {storedAuthSummary(product, connector)}
        </span>
        <div className="jira-setup__options">
          <Option
            name={id(modeField)}
            value="cloud"
            checked={locationValue === "cloud"}
            onChoose={() => chooseLocation("cloud")}
            title="Atlassian Cloud"
            help={`${name} at https://your-site.atlassian.net, signed in with an account email and an API token.`}
          />
          <Option
            name={id(modeField)}
            value="own"
            checked={locationValue === "own"}
            onChoose={() => chooseLocation("own")}
            title="Own instance (Server / Data Center)"
            help={`A ${name} your organisation hosts, signed in with a username and password, a personal access token or OpenID Connect client credentials.`}
          />
        </div>
        {!view.location || view.location === "cloud" ? (
          <FieldError error={shown(modeField)} />
        ) : null}
      </div>
  );
}

export function AtlassianOwnMethodGroup({ fc, modeField, locationKey, chooseMethod }: {
  fc: AtlassianFieldContext;
  modeField: string;
  locationKey: string;
  chooseMethod: (mode: AtlassianAuthMode) => void;
}) {
  const { product, view, id, shown } = fc;
  return (
        <div
          className="connector-field jira-setup__group"
          role="radiogroup"
          aria-labelledby={`${id(locationKey)}-label`}
        >
          <span
            id={`${id(locationKey)}-label`}
            className="connector-field__label"
          >
            How your own instance signs in
          </span>
          <div className="jira-setup__options">
            {OWN_INSTANCE_MODES.map((mode) => (
              <Option
                key={mode}
                name={id(locationKey)}
                value={mode}
                checked={view.mode === mode}
                onChoose={() => chooseMethod(mode)}
                title={authModeFields(product, mode).label}
                help={authModeFields(product, mode).help}
              />
            ))}
          </div>
          <FieldError error={shown(modeField)} />
        </div>
  );
}

function MethodSwitchNote({ secretLabel }: { secretLabel: string }) {
  return (
            <span
              className="security-field-hint security-field-hint--attention"
              role="note"
            >
              The sign-in method changes: enter a new{" "}
              {secretLabel.toLowerCase()}. Only the chosen method&apos;s
              secret is used after saving.
            </span>
  );
}

type OidcProps = Parameters<typeof OidcTokenUrlField>[0];

export function AtlassianCredentialFields({ fc, mode, oidc }: {
  fc: AtlassianFieldContext;
  mode: AtlassianAuthMode;
  oidc: OidcProps | null;
}) {
  const { product, name, draft, view, set, rebind, id, shown } = fc;
  const fields = authModeFields(product, mode);
  return (
        <>
          {mode === "cloud_api_token" ? (
            <span className="ds-sr-only">{fields.help}</span>
          ) : null}
          {view.switching ? <MethodSwitchNote secretLabel={fields.secretLabel} /> : null}
          {oidc ? <OidcTokenUrlField {...oidc} /> : null}
          {fields.principal ? (
            <CredentialInput
              field={fields.principal}
              label={fields.principalLabel}
              type={mode === "cloud_api_token" ? "email" : "text"}
              value={draft[fields.principal] ?? ""}
              placeholder={
                mode === "cloud_api_token"
                  ? "name@example.com"
                  : oidc
                    ? ""
                    : `${name} username`
              }
              error={shown(fields.principal)}
              id={id}
              rebind={rebind}
              onChange={set}
            />
          ) : null}
          <CredentialInput
            field={fields.secret}
            label={fields.secretLabel}
            type="password"
            secret
            value={draft[fields.secret] ?? ""}
            placeholder={
              view.secretKeepable
                ? "••••••• (stored — leave blank to keep)"
                : `Enter the ${fields.secretLabel.toLowerCase()}`
            }
            error={shown(fields.secret)}
            id={id}
            rebind={rebind}
            onChange={set}
          />
          {oidc ? <OidcOptionalFields {...oidc} /> : null}
        </>
  );
}
