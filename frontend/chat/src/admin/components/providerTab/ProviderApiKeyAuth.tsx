import type { ProviderTabCtx } from "./types";

type ProviderApiKeyAuthProps = {
  ctx: ProviderTabCtx;
  provider: any;
};

export function ProviderApiKeyAuth({
  ctx,
  provider: p,
}: ProviderApiKeyAuthProps) {
  const {
    editingKey,
    handleSaveApiKey,
    newKeyValue,
    setEditingKey,
    setNewKeyValue,
  } = ctx;

  return (
    <div className="provider-card__key-row">
      <span className="provider-card__key-label">API Key</span>
      {editingKey === p.id ? (
        <div className="provider-card__key-edit">
          <input
            type="password"
            placeholder="Enter new API key"
            value={newKeyValue}
            onChange={(e) => setNewKeyValue(e.target.value)}
            className="provider-card__key-input"
          />
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            onClick={() => void handleSaveApiKey(p.id)}
          >
            Save
          </button>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => {
              setEditingKey(null);
              setNewKeyValue("");
            }}
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="provider-card__key-display">
          <span className="provider-card__key-masked">
            {p.has_api_key ? p.api_key_masked : "Not set"}
          </span>
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => {
              setEditingKey(p.id);
              setNewKeyValue("");
            }}
          >
            {p.has_api_key ? "Change" : "Set Key"}
          </button>
        </div>
      )}
    </div>
  );
}
