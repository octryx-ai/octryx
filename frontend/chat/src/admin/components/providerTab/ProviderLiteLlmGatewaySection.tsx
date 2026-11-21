import { useMemo, useState } from "react";
import { FormSection } from "../../../layout/FormSection";
import { PanelFooterActions } from "../../../layout/PanelFooterSlot";
import { StatusLabel } from "../../../layout/StatusLabel";
import { LiteLlmGatewayConfigFields } from "./LiteLlmGatewayConfigFields";
import { LiteLlmGatewaySecretNotice } from "./LiteLlmGatewaySecretNotice";
import { buildGatewayUpdatePayload } from "./litellmGatewayPayload";
import { gatewayDraftFromProvider } from "./litellmGatewayDrafts";
import { isGatewayDraftSubmittable } from "./litellmGatewayValidation";
import { presentProviderReadiness } from "./litellmGatewayReadiness";
import type { GatewayDraft } from "./litellmGatewayTypes";
import type { ProviderTabCtx } from "./types";

// The governed gateway in the provider's side panel: its state in words (the fixed code is the
// tooltip), the gateway fields, the key's linked flag, and Reset / Save changes in the panel footer, bottom right.
// What each field means is in the Providers help (help/admin/providers.md).

type ProviderLiteLlmGatewaySectionProps = {
  ctx: ProviderTabCtx;
  provider: {
    id: string;
    display_name?: string;
    endpoint_url?: string;
    has_api_key?: boolean;
    config_json?: unknown;
    readiness?: {
      status?: unknown;
      reason?: unknown;
      runtime_attempt_allowed?: unknown;
    };
    readiness_status?: unknown;
    readiness_reason?: unknown;
  };
};

const READINESS_TONES = { ready: "neutral", blocked: "attention", unknown: "neutral" } as const;

export function ProviderLiteLlmGatewaySection({
  ctx,
  provider,
}: ProviderLiteLlmGatewaySectionProps) {
  const { handleUpdateLiteLlmGatewayProvider } = ctx;
  const idPrefix = `litellm-gateway-${provider.id}`;

  const stored = useMemo(() => gatewayDraftFromProvider(provider), [provider]);
  const [draft, setDraft] = useState<GatewayDraft>(stored);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  const readiness = presentProviderReadiness(
    provider.readiness ?? {
      status: provider.readiness_status,
      reason: provider.readiness_reason,
    },
  );
  const submittable = isGatewayDraftSubmittable(draft);

  const handleSave = () =>
    saveGateway({ submittable, draft, provider, handleUpdateLiteLlmGatewayProvider, setSaving, setError, setSaved });

  return (
    <div className="litellm-gateway__section" data-testid="litellm-gateway-section">
      <GatewayState readiness={readiness} secretRefConfigured={Boolean(provider.has_api_key)} idPrefix={idPrefix} />

      <LiteLlmGatewayConfigFields
        draft={draft}
        onChange={(next) => {
          setDraft(next);
          setSaved(false);
        }}
        idPrefix={idPrefix}
      />

      {error ? <div className="admin-panel__error" role="alert">{error}</div> : null}
      {saved ? (
        <p className="admin-panel__success" role="status">
          Saved. The state above updates with the next check.
        </p>
      ) : null}

      <GatewayFooter saving={saving} submittable={submittable} onSave={() => void handleSave()} onReset={() => {
        setDraft(stored);
        setError(null);
        setSaved(false);
      }} />
    </div>
  );
}

// Saves the draft when it is complete; the server's refusal is shown above the buttons.
async function saveGateway({ submittable, draft, provider, handleUpdateLiteLlmGatewayProvider, setSaving, setError, setSaved }: {
  submittable: boolean;
  draft: GatewayDraft;
  provider: ProviderLiteLlmGatewaySectionProps["provider"];
  handleUpdateLiteLlmGatewayProvider: ProviderTabCtx["handleUpdateLiteLlmGatewayProvider"];
  setSaving: (saving: boolean) => void;
  setError: (error: string | null) => void;
  setSaved: (saved: boolean) => void;
}) {
  if (!submittable) {
    setSaved(false);
    setError("Some fields are incomplete. Fix the points listed above the buttons.");
    return;
  }
  setSaving(true);
  setError(null);
  setSaved(false);
  const result = await handleUpdateLiteLlmGatewayProvider(
    provider.id,
    buildGatewayUpdatePayload(draft, provider.config_json),
  );
  setSaving(false);
  if (result.ok) {
    setSaved(true);
    return;
  }
  setError(result.error);
  
}

// The gateway's state in words (the fixed code is the tooltip) and whether its key is linked.
function GatewayState({ readiness, secretRefConfigured, idPrefix }: {
  readiness: ReturnType<typeof presentProviderReadiness>;
  secretRefConfigured: boolean;
  idPrefix: string;
}) {
  return (
    <FormSection title="State">
      <p className="litellm-gateway__state" role="status" title={readiness.code}>
        <StatusLabel label={readiness.statusLabel} tone={READINESS_TONES[readiness.tone]} />
        <span>{readiness.label}</span>
      </p>
      <LiteLlmGatewaySecretNotice
        secretRefConfigured={secretRefConfigured}
        idPrefix={idPrefix}
      />
    </FormSection>
  );
}

// Reset and Save changes in the panel footer, bottom right.
function GatewayFooter({ saving, submittable, onSave, onReset }: {
  saving: boolean; submittable: boolean; onSave: () => void; onReset: () => void;
}) {
  return (
    <PanelFooterActions>
      <button
        type="button"
        className="admin-panel__action-btn"
        onClick={onReset}
        disabled={saving}
      >
        Reset
      </button>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={onSave}
        disabled={saving || !submittable}
        data-testid="litellm-gateway-save"
      >
        {saving ? "Saving…" : "Save changes"}
      </button>
    </PanelFooterActions>
  );
}
