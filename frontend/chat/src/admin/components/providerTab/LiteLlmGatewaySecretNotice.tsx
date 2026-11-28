// Intentionally disabled: no Admin API accepts an existing secret reference, and asking for the virtual key
// in the browser is exactly what the gateway contract forbids.

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
