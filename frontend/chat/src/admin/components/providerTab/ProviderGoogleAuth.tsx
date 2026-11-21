import type { ProviderTabCtx } from "./types";

type ProviderGoogleAuthProps = {
  ctx: ProviderTabCtx;
  provider: any;
};

// Google login: who is connected and the (re)connect button.
function GoogleLoginStatus({ ctx, provider: p }: ProviderGoogleAuthProps) {
  const { googleConnectLoading, handleGoogleConnect } = ctx;
  return (
    <>
      <span className="provider-card__key-masked">
        {p.auth_login
          ? `${p.auth_name || p.auth_login} · ${p.google_cloud_project || "no project"}`
          : "Not connected"}
      </span>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={() => handleGoogleConnect(p.id)}
        disabled={googleConnectLoading === p.id}
      >
        {googleConnectLoading === p.id
          ? "Redirecting…"
          : p.auth_login
            ? "Reconnect with Google"
            : "Connect with Google"}
      </button>
    </>
  );
}

// The Gemini API key being typed, with Save and Cancel.
function GoogleKeyEditor({ ctx, provider: p }: ProviderGoogleAuthProps) {
  const { handleSaveApiKey, newKeyValue, setEditingKey, setNewKeyValue } = ctx;
  return (
    <div className="provider-card__key-edit">
      <input
        type="password"
        placeholder="Enter Gemini API key"
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
  );
}

// The stored Gemini API key, masked, and the button that starts editing it.
function GoogleKeyDisplay({ ctx, provider: p }: ProviderGoogleAuthProps) {
  const { setEditingKey, setNewKeyValue } = ctx;
  return (
    <>
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
    </>
  );
}

// The provider's Gemini access: Google login, or a Gemini API key shown masked and edited in place.
function GoogleKeyRow({ ctx, provider: p }: ProviderGoogleAuthProps) {
  return (
    <div className="provider-card__key-row">
      <span className="provider-card__key-label">Google Gemini</span>
      <div
        className="provider-card__key-display"
        style={{ flexWrap: "wrap", gap: "0.5rem" }}
      >
        {p.auth_mode === "oauth" ? (
          <GoogleLoginStatus ctx={ctx} provider={p} />
        ) : ctx.editingKey === p.id ? (
          <GoogleKeyEditor ctx={ctx} provider={p} />
        ) : (
          <GoogleKeyDisplay ctx={ctx} provider={p} />
        )}
      </div>
    </div>
  );
}

// One OAuth config field, written to the provider's draft.
function DraftInput({ type, placeholder, value, onValue }: {
  type: "text" | "password";
  placeholder: string;
  value: string;
  onValue: (value: string) => void;
}) {
  return (
    <input
      type={type}
      placeholder={placeholder}
      value={value}
      onChange={(e) => onValue(e.target.value)}
      className="provider-card__key-input"
    />
  );
}

// The OAuth client and Cloud project the Google login uses, saved as the provider's config.
function GoogleOAuthConfigRow({ ctx, provider: p }: ProviderGoogleAuthProps) {
  const { handleProviderDraftChange, handleSaveGoogleProviderConfig, providerDrafts, savingProviderConfig } = ctx;
  const change = (field: string) => (value: string) => handleProviderDraftChange(p.id, field, value);
  return (
    <div className="provider-card__key-row">
      <span className="provider-card__key-label">OAuth Config</span>
      <div className="provider-card__key-edit">
        <select
          className="provider-card__key-input"
          value={providerDrafts[p.id]?.auth_mode || p.auth_mode || "api_key"}
          onChange={(e) =>
            handleProviderDraftChange(p.id, "auth_mode", e.target.value)
          }
        >
          <option value="oauth">Google login</option>
          <option value="api_key">Gemini API key</option>
        </select>
        <DraftInput
          type="text"
          placeholder="Google OAuth Client ID"
          value={providerDrafts[p.id]?.google_oauth_client_id || p.google_oauth_client_id || ""}
          onValue={change("google_oauth_client_id")}
        />
        <DraftInput
          type="password"
          placeholder={
            p.google_oauth_client_configured
              ? "Leave blank to keep current client secret"
              : "Google OAuth Client Secret"
          }
          value={providerDrafts[p.id]?.google_oauth_client_secret || ""}
          onValue={change("google_oauth_client_secret")}
        />
        <DraftInput
          type="text"
          placeholder="Google Cloud Project"
          value={providerDrafts[p.id]?.google_cloud_project || p.google_cloud_project || ""}
          onValue={change("google_cloud_project")}
        />
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void handleSaveGoogleProviderConfig(p.id)}
          disabled={savingProviderConfig === p.id}
        >
          {savingProviderConfig === p.id ? "Saving…" : "Save Config"}
        </button>
      </div>
    </div>
  );
}

export function ProviderGoogleAuth({
  ctx,
  provider,
}: ProviderGoogleAuthProps) {
  return (
    <>
      <GoogleKeyRow ctx={ctx} provider={provider} />
      <GoogleOAuthConfigRow ctx={ctx} provider={provider} />
    </>
  );
}
