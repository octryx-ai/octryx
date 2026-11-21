// API keys section of the user edit panel: the one-time secret, the create form and the key list with revoke.
import type { FormEvent } from "react";
import { formatDateTime } from "../../utils/dateTime";
import type { AdminUserApiKeyRow } from "./identityTypes";
import { SectionLabel } from "./userEditPanelParts";

function formatDate(v: string | null) {
  if (!v) return "Never";
  return formatDateTime(v);
}
type Props = {
  apiKeys: AdminUserApiKeyRow[];
  apiKeyName: string;
  apiKeyScopes: string;
  apiKeyExpiresAt: string;
  apiKeyCreatedSecret: string | null;
  apiKeyError: string | null;
  apiKeyLoading: string | null;
  setApiKeyName: (v: string) => void;
  setApiKeyScopes: (v: string) => void;
  setApiKeyExpiresAt: (v: string) => void;
  onCreateApiKey: (event: FormEvent) => void;
  onRevokeApiKey: (key: AdminUserApiKeyRow) => void;
};

// The create form: name, optional scopes and expiry.
function ApiKeyForm({ apiKeyName, apiKeyScopes, apiKeyExpiresAt, apiKeyLoading, setApiKeyName, setApiKeyScopes, setApiKeyExpiresAt, onCreateApiKey }: Omit<Props, "apiKeys" | "apiKeyCreatedSecret" | "apiKeyError" | "onRevokeApiKey">) {
  return (
    <form
      className="user-edit-panel__apikey-form"
      onSubmit={onCreateApiKey}
    >
      <label className="user-edit-panel__apikey-field">
        <span>
          Key name <span className="user-edit-panel__required">*</span>
        </span>
        <input
          value={apiKeyName}
          onChange={(e) => setApiKeyName(e.target.value)}
          placeholder="e.g. CI pipeline key"
          required
        />
      </label>
      <label className="user-edit-panel__apikey-field">
        <span>
          Scopes{" "}
          <span className="user-edit-panel__hint-inline">
            (optional, comma-separated)
          </span>
        </span>
        <input
          value={apiKeyScopes}
          onChange={(e) => setApiKeyScopes(e.target.value)}
          placeholder="e.g. read, write"
        />
      </label>
      <label className="user-edit-panel__apikey-field user-edit-panel__apikey-field--full">
        <span>
          Expires at{" "}
          <span className="user-edit-panel__hint-inline">
            (optional — leave empty for no expiry)
          </span>
        </span>
        <input
          type="datetime-local"
          value={apiKeyExpiresAt}
          onChange={(e) => setApiKeyExpiresAt(e.target.value)}
        />
      </label>
      <button
        type="submit"
        className="admin-panel__action-btn admin-panel__action-btn--primary user-edit-panel__apikey-field--full"
        disabled={!!apiKeyLoading?.startsWith("create:")}
      >
        {apiKeyLoading?.startsWith("create:")
          ? "Creating…"
          : "Create key"}
      </button>
    </form>
  );
}

// One row per key with its state and revoke, or the empty line.
function ApiKeyRows({ apiKeys, apiKeyLoading, onRevokeApiKey }: Pick<Props, "apiKeys" | "apiKeyLoading" | "onRevokeApiKey">) {
  return apiKeys.length > 0 ? (
      <div className="user-edit-panel__apikey-list">
        {apiKeys.map((key) => (
          <div key={key.id} className="user-edit-panel__apikey-row">
            <div className="user-edit-panel__apikey-info">
              <strong>{key.name}</strong>
              <span className="admin-panel__cell--muted">
                {key.key_prefix} · Last used{" "}
                {formatDate(key.last_used_at)} · Expires{" "}
                {formatDate(key.expires_at)}
              </span>
            </div>
            <div className="user-edit-panel__apikey-actions">
              <span
                className={`admin-panel__badge ${key.revoked_at ? "admin-panel__badge--inactive" : "admin-panel__badge--active"}`}
              >
                {key.revoked_at ? "Revoked" : "Active"}
              </span>
              {!key.revoked_at && (
                <button
                  type="button"
                  className="admin-panel__danger-btn"
                  onClick={() => onRevokeApiKey(key)}
                  disabled={apiKeyLoading === `revoke:${key.id}`}
                >
                  {apiKeyLoading === `revoke:${key.id}`
                    ? "Revoking…"
                    : "Revoke"}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    ) : (
      <p
        className="admin-panel__cell--muted"
        style={{ fontSize: "var(--ds-text-sm)" }}
      >
        No API keys yet.
      </p>
  );
}

export function AdminUserApiKeysSection({ apiKeys, apiKeyCreatedSecret, apiKeyError, apiKeyLoading, onRevokeApiKey, ...form }: Props) {
  return (
    <section className="user-edit-panel__section">
      <SectionLabel>API keys</SectionLabel>
      {apiKeyError && <p className="admin-panel__error">{apiKeyError}</p>}
      {apiKeyCreatedSecret && (
        <div className="admin-users__secret-once">
          <strong>Copy this key — it will not be shown again.</strong>
          <code>{apiKeyCreatedSecret}</code>
        </div>
      )}
      <ApiKeyForm apiKeyLoading={apiKeyLoading} {...form} />

      <ApiKeyRows apiKeys={apiKeys} apiKeyLoading={apiKeyLoading} onRevokeApiKey={onRevokeApiKey} />
    </section>
  );
}
