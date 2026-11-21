// Virtual-key state for a governed LiteLLM gateway provider.
//
// The control is intentionally disabled. The gateway virtual key is reachable
// only through `LLMProvider.api_key_secret_ref`, and no canonical Admin API
// accepts an existing secret reference: every provider write path
// (`POST/PUT /chat/api/panel/providers`, the control-plane provider form)
// takes a plaintext `api_key` and mints a new secret from it. Offering an input
// here would mean asking an operator to paste the master/virtual key into the
// browser, which is exactly what the gateway contract forbids — so the field
// stays disabled and the gap is stated instead of worked around. What it means
// is in the Providers help; the field's tooltip says it in one line.

type LiteLlmGatewaySecretNoticeProps = {
  secretRefConfigured: boolean;
  idPrefix: string;
};

export function LiteLlmGatewaySecretNotice({
  secretRefConfigured,
  idPrefix,
}: LiteLlmGatewaySecretNoticeProps) {
  const inputId = `${idPrefix}-virtual-key-ref`;

  return (
    <label className="admin-panel__field" htmlFor={inputId}>
      <span>Gateway key</span>
      <input
        id={inputId}
        className="admin-panel__input"
        value={secretRefConfigured ? "Secret Reference linked" : "Not linked"}
        readOnly
        disabled
        title="The key is never shown here, only whether it is linked. A platform operator links it on the server."
      />
    </label>
  );
}
