import type { ProviderTabCtx } from "./types";

type ProviderBedrockPromptCachingProps = {
  ctx: ProviderTabCtx;
  provider: any;
};

export function ProviderBedrockPromptCaching({
  ctx,
  provider: p,
}: ProviderBedrockPromptCachingProps) {
  const {
    handleProviderDraftChange,
    handleSaveBedrockProviderConfig,
    providerDrafts,
    savingProviderConfig,
  } = ctx;
  const draft = providerDrafts[p.id] || {};
  const enabled = draft.bedrock_prompt_cache_enabled === "true";
  // Every text field writes its value under its draft key.
  const change = (key: string) => (event: { target: { value: string } }) =>
    handleProviderDraftChange(p.id, key, event.target.value);

  return (
    <div className="provider-card__key-row">
      <span className="provider-card__key-label">Bedrock</span>
      <div className="provider-card__key-edit" style={{ flexWrap: "wrap" }}>
        <span className="provider-card__key-masked">
          Static credentials:{" "}
          {p.aws_static_credentials_configured ? "Configured" : "Not set"}
        </span>
        <BedrockFields draft={draft} enabled={enabled} change={change}
          onEnabled={(checked) => handleProviderDraftChange(p.id, "bedrock_prompt_cache_enabled", checked ? "true" : "false")} />
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void handleSaveBedrockProviderConfig(p)}
          disabled={savingProviderConfig === p.id}
        >
          {savingProviderConfig === p.id ? "Saving…" : "Save Bedrock Config"}
        </button>
      </div>
    </div>
  );
}

type Change = (key: string) => (event: { target: { value: string } }) => void;

// The static credentials and the prompt cache settings of the draft.
function BedrockFields({ draft, enabled, change, onEnabled }: {
  draft: Record<string, string | undefined>;
  enabled: boolean;
  change: Change;
  onEnabled: (checked: boolean) => void;
}) {
  return (
    <>
      <input
        placeholder="AWS Access Key ID"
        value={draft.aws_access_key_id || ""}
        onChange={change("aws_access_key_id")}
        className="provider-card__key-input"
      />
      <input
        type="password"
        placeholder="AWS Secret Access Key"
        value={draft.aws_secret_access_key || ""}
        onChange={change("aws_secret_access_key")}
        className="provider-card__key-input"
      />
      <input
        type="password"
        placeholder="AWS Session Token (optional)"
        value={draft.aws_session_token || ""}
        onChange={change("aws_session_token")}
        className="provider-card__key-input"
      />
      <label className="admin-panel__inline-toggle">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => onEnabled(event.target.checked)}
        />
        <span>Bedrock cache enabled</span>
      </label>
      <select
        value={draft.bedrock_prompt_cache_ttl || "5m"}
        onChange={change("bedrock_prompt_cache_ttl")}
        className="provider-card__key-input"
      >
        <option value="5m">TTL: 5 minutes</option>
        <option value="1h">TTL: 1 hour</option>
      </select>
      <input
        type="number"
        min="1"
        step="1"
        placeholder="Min tokens"
        value={draft.bedrock_prompt_cache_min_tokens || ""}
        onChange={change("bedrock_prompt_cache_min_tokens")}
        className="provider-card__key-input"
      />
    </>
  );
}
