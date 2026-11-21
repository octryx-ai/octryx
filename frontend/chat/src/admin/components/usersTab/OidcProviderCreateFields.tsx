// The provider fields of the Register OIDC provider form.
import type { Dispatch, SetStateAction } from "react";

import type { NewOidcProvider } from "./oidcProviderDraft";

type FieldSpec = {
  key: keyof NewOidcProvider;
  label: string;
  required?: boolean;
  secret?: boolean;
  placeholder?: string;
};

const FIELDS: FieldSpec[] = [
  { key: "name", label: "Provider name", required: true },
  { key: "issuerUrl", label: "Issuer URL" },
  { key: "discoveryUrl", label: "Discovery URL (optional)", placeholder: "e.g. https://login.example.com/.well-known/openid-configuration" },
  { key: "clientId", label: "Client ID" },
  { key: "clientSecret", label: "Client secret", secret: true, placeholder: "Stored securely" },
  { key: "scopes", label: "Scopes" },
];

export function OidcProviderCreateFields({ value, onChange }: {
  value: NewOidcProvider;
  onChange: Dispatch<SetStateAction<NewOidcProvider>>;
}) {
  return (
    <>
      {FIELDS.map((field) => (
        <label key={field.key} className="admin-panel__field">
          <span>{field.label}</span>
          <input
            type={field.secret ? "password" : undefined}
            className="admin-panel__input"
            required={field.required}
            value={value[field.key]}
            onChange={(event) =>
              onChange((current) => ({
                ...current,
                [field.key]: event.target.value,
              }))
            }
            autoComplete={field.secret ? "off" : undefined}
            placeholder={field.placeholder}
          />
        </label>
      ))}
    </>
  );
}
