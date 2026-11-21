import { SecretRebindFieldHint } from "../../secretRebind/SecretRebindFieldHint";
import { rebindFieldClass } from "../../secretRebind/secretRebindFlow";
import type { ConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";

// One labelled connector credential input with its help, error and secret-rebind hint (shared by the guided
// Atlassian, OpenID Connect and ServiceNow sign-in fields).

export type CredentialFieldError = { message: string; live: boolean };

function errorClass(error: CredentialFieldError | null): string {
  return error ? " security-field--error" : "";
}

export function FieldError({ error }: { error: CredentialFieldError | null }) {
  if (!error) return null;
  return (
    <span className="security-field-hint security-field-hint--error">
      {error.message}
    </span>
  );
}

export function CredentialInput({
  field,
  label,
  type,
  secret = false,
  value,
  placeholder,
  help,
  error,
  id,
  rebind,
  onChange,
}: {
  field: string;
  label: string;
  type: string;
  secret?: boolean;
  value: string;
  placeholder: string;
  help?: string;
  error: CredentialFieldError | null;
  id: (field: string) => string;
  rebind: Pick<ConnectorSecretRebind, "flow">;
  onChange: (field: string, value: string) => void;
}) {
  return (
    <div className="connector-field">
      <label className="connector-field__label" htmlFor={id(field)}>
        {label}
        {secret ? (
          <span className="connector-field__secret-badge">secret</span>
        ) : null}
      </label>
      <input
        id={id(field)}
        type={type}
        className={`connector-field__input${errorClass(error)}${rebindFieldClass(rebind.flow, field)}`}
        value={value}
        onChange={(event) => onChange(field, event.target.value)}
        placeholder={placeholder}
        aria-invalid={Boolean(error)}
        aria-describedby={help ? `${id(field)}-help` : undefined}
        title={help || undefined}
        autoComplete="off"
      />
      {/* The explanation is the field's description for assistive technology and its tooltip;
          the page's help says it in full. No help sentence under every field. */}
      {help ? <span id={`${id(field)}-help`} className="ds-sr-only">{help}</span> : null}
      <FieldError error={error} />
      <SecretRebindFieldHint flow={rebind.flow} field={field} />
    </div>
  );
}

/** One radio choice with its title; its one-line help is the tooltip and the description for assistive technology. */
export function Option({
  name,
  value,
  checked,
  onChoose,
  title,
  help,
}: {
  name: string;
  value: string;
  checked: boolean;
  onChoose: () => void;
  title: string;
  help: string;
}) {
  return (
    <label className="jira-setup__option" title={help}>
      <input
        type="radio"
        name={name}
        value={value}
        checked={checked}
        onChange={onChoose}
      />
      <span className="jira-setup__option-text">
        <strong>{title}</strong>
        <span className="ds-sr-only"> · {help}</span>
      </span>
    </label>
  );
}
