import type { ProviderTabCtx } from "./types";

type ProvidersLocalBootstrapCardProps = {
  ctx: ProviderTabCtx;
};

// The endpoint, model and display name drafts.
function BootstrapFields({ ctx }: ProvidersLocalBootstrapCardProps) {
  const {
    localBootstrapDisplayDraft,
    localBootstrapEndpointDraft,
    localBootstrapModelDraft,
    setLocalBootstrapDisplayDraft,
    setLocalBootstrapEndpointDraft,
    setLocalBootstrapModelDraft,
  } = ctx;
  return (
    <div className="provider-anchor__fields">
      <label className="admin-panel__form-label">
        Ollama endpoint
        <input
          value={localBootstrapEndpointDraft}
          onChange={(event) =>
            setLocalBootstrapEndpointDraft(event.target.value)
          }
          placeholder="http://localhost:11434"
        />
      </label>
      <label className="admin-panel__form-label">
        Bootstrap model
        <input
          value={localBootstrapModelDraft}
          onChange={(event) =>
            setLocalBootstrapModelDraft(event.target.value)
          }
          placeholder="gemma4"
        />
      </label>
      <label className="admin-panel__form-label">
        Display name
        <input
          value={localBootstrapDisplayDraft}
          onChange={(event) =>
            setLocalBootstrapDisplayDraft(event.target.value)
          }
          placeholder="Local Gemma 4 Anchor"
        />
      </label>
    </div>
  );
}

// Pull the model automatically, and make the anchor the primary runtime.
function BootstrapOptions({ ctx }: ProvidersLocalBootstrapCardProps) {
  const { localBootstrapMakePrimary, localBootstrapPullModel, setLocalBootstrapMakePrimary, setLocalBootstrapPullModel } = ctx;
  return (
    <div className="provider-anchor__options">
      <label className="admin-panel__checkbox">
        <input
          type="checkbox"
          checked={localBootstrapPullModel}
          onChange={(event) =>
            setLocalBootstrapPullModel(event.target.checked)
          }
        />
        <span>Pull model automatically</span>
      </label>
      <label className="admin-panel__checkbox">
        <input
          type="checkbox"
          checked={localBootstrapMakePrimary}
          onChange={(event) =>
            setLocalBootstrapMakePrimary(event.target.checked)
          }
        />
        <span>Set as primary runtime</span>
      </label>
    </div>
  );
}

// Check and install, with the local status beside them.
function BootstrapActions({ ctx }: ProvidersLocalBootstrapCardProps) {
  const { handleCheckLocalBootstrap, handleSetupLocalBootstrap, localBootstrap, localBootstrapActionLoading, localBootstrapLoading } = ctx;
  return (
      <div className="provider-anchor__actions">
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={() => void handleCheckLocalBootstrap()}
          disabled={localBootstrapActionLoading === "health"}
        >
          {localBootstrapActionLoading === "health"
            ? "Checking…"
            : "Check Ollama"}
        </button>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void handleSetupLocalBootstrap()}
          disabled={localBootstrapActionLoading === "setup"}
        >
          {localBootstrapActionLoading === "setup"
            ? "Bootstrapping…"
            : "Install Gemma 4 Anchor"}
        </button>
        {localBootstrapLoading ? (
          <span className="provider-card__meta">Loading local status…</span>
        ) : localBootstrap ? (
          <span className="provider-card__meta provider-anchor__status">
            {localBootstrap.setup_complete ? "Configured" : "Not configured"}{" "}
            · {localBootstrap.health_status || "unknown"} ·{" "}
            {localBootstrap.endpoint_url ||
              localBootstrap.recommended_endpoint_url}
            {localBootstrap.available_models.length
              ? ` · models: ${localBootstrap.available_models.slice(0, 4).join(", ")}`
              : ""}
          </span>
        ) : null}
      </div>
  );
}

// The current anchor, the endpoint notes and the last error.
function BootstrapStatus({ ctx }: ProvidersLocalBootstrapCardProps) {
  const { localBootstrap, localBootstrapError } = ctx;
  return (
    <>
      {localBootstrap && (
        <div className="provider-card__meta provider-anchor__status-line">
          Current anchor:{" "}
          {localBootstrap.provider_display_name || "not configured"} · model{" "}
          {localBootstrap.model_id ||
            localBootstrap.recommended_model_id ||
            "gemma4"}{" "}
          · {localBootstrap.is_primary ? "primary runtime" : "not primary"}
          {localBootstrap.last_health_error
            ? ` · ${localBootstrap.last_health_error}`
            : ""}
        </div>
      )}
      <div className="provider-card__meta provider-anchor__notes">
        Host setups should usually use <code>http://localhost:11434</code>.
        Docker setups can use <code>http://ollama:11434</code>. A plain{" "}
        <code>gemma4</code> request is resolved to an installed Gemma 4
        variant such as <code>gemma4:e4b</code>.
      </div>
      {localBootstrapError && (
        <div className="admin-panel__error">{localBootstrapError}</div>
      )}
    </>
  );
}

export function ProvidersLocalBootstrapCard({
  ctx,
}: ProvidersLocalBootstrapCardProps) {
  const {
    localBootstrap,
    localBootstrapEndpointDraft,
    localBootstrapLoading,
    localBootstrapModelDraft,
  } = ctx;

  const hasOllamaProvider =
    Array.isArray(ctx.providers) &&
    (ctx.providers as any[]).some((p) => p.driver === "ollama");
  const hasDraft =
    localBootstrapEndpointDraft.trim() || localBootstrapModelDraft.trim();

  if (
    !localBootstrapLoading &&
    !localBootstrap &&
    !hasDraft &&
    !hasOllamaProvider
  ) {
    return null;
  }

  return (
    <div
      className="provider-card provider-card--anchor"
      style={{ marginBottom: "1rem" }}
    >
      <div className="provider-card__body provider-anchor">
        <div>
          <div className="provider-card__name">Local Gemma 4 Anchor</div>
          <div className="provider-card__meta provider-anchor__summary">
            Bootstrap a local Ollama runtime that becomes the standard anchor
            for new systems. It can guide initial setup before additional API or
            CLI runtimes are configured.
          </div>
        </div>
        <BootstrapFields ctx={ctx} />
        <BootstrapOptions ctx={ctx} />
        <BootstrapActions ctx={ctx} />
        <BootstrapStatus ctx={ctx} />
      </div>
    </div>
  );
}
