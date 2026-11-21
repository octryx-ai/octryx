// The provider-type chooser, shared by the generic add-provider form and the
// governed LiteLLM gateway form so both offer exactly the same catalog. The catalog
// itself lives in providerCreateChoices.ts, which is the single place a driver
// choice may be added — and which carries no driver the backend removed.

import { PROVIDER_CREATE_CHOICES } from "./providerCreateChoices";

type ProviderTypeSelectProps = {
  value: string;
  onChange: (value: string) => void;
};

export function ProviderTypeSelect({
  value,
  onChange,
}: ProviderTypeSelectProps) {
  return (
    <label className="admin-panel__field" htmlFor="provider-type">
      <span>Provider type</span>
      <select
        id="provider-type"
        className="admin-panel__input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {PROVIDER_CREATE_CHOICES.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
    </label>
  );
}
