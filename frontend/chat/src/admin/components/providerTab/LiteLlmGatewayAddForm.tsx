import { useEffect, useState } from "react";
import { LiteLlmGatewayConfigFields } from "./LiteLlmGatewayConfigFields";
import { LiteLlmGatewaySecretNotice } from "./LiteLlmGatewaySecretNotice";
import { buildGatewayCreatePayload } from "./litellmGatewayPayload";
import { emptyGatewayDraft } from "./litellmGatewayDrafts";
import { isGatewayDraftSubmittable } from "./litellmGatewayValidation";
import type { GatewayDraft } from "./litellmGatewayTypes";
import type { ProviderTabCtx } from "./types";

// Add-provider form for the governed LiteLLM gateway.
//
// It owns its own draft instead of widening the shared provider form state, and
// it submits only the canonical fields `buildGatewayCreatePayload` produces —
// never a credential field.

const ID_PREFIX = "litellm-gateway-new";

// What the add-provider panel's footer button needs: it submits this form through `form=`.
export type GatewayFormState = { saving: boolean; submittable: boolean };

type LiteLlmGatewayAddFormProps = {
  ctx: ProviderTabCtx;
  formId: string;
  onStateChange: (state: GatewayFormState) => void;
};

// The form's own draft, its error and saving state (reported to the panel's footer), and the submit that creates
// the provider from the canonical payload.
function useGatewayDraft(ctx: ProviderTabCtx, onStateChange: (state: GatewayFormState) => void) {
  const { handleCreateLiteLlmGatewayProvider, newProviderDisplay, setNewProviderDisplay } = ctx;

  const [draft, setDraft] = useState<GatewayDraft>(emptyGatewayDraft());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submittable = isGatewayDraftSubmittable({
    ...draft,
    displayName: newProviderDisplay,
  });
  useEffect(() => {
    onStateChange({ saving, submittable });
  }, [onStateChange, saving, submittable]);

  const handleSubmit = async (event: { preventDefault: () => void }) => {
    event.preventDefault();
    const candidate: GatewayDraft = {
      ...draft,
      displayName: newProviderDisplay,
    };
    if (!isGatewayDraftSubmittable(candidate)) {
      setError(
        "The governed fields are incomplete. Resolve the listed codes before saving.",
      );
      return;
    }
    setSaving(true);
    setError(null);
    const result = await handleCreateLiteLlmGatewayProvider(
      buildGatewayCreatePayload(candidate),
    );
    setSaving(false);
    if (result.ok) {
      setDraft(emptyGatewayDraft());
      setNewProviderDisplay("");
      return;
    }
    setError(result.error);
  };

  return { draft, setDraft, error, handleSubmit };
}

export function LiteLlmGatewayAddForm({ ctx, formId, onStateChange }: LiteLlmGatewayAddFormProps) {
  const { newProviderDisplay, setNewProviderDisplay } = ctx;

  const { draft, setDraft, error, handleSubmit } = useGatewayDraft(ctx, onStateChange);

  return (
    <form
      id={formId}
      className="provider-form litellm-gateway__form"
      onSubmit={(e) => void handleSubmit(e)}
    >
      <label className="admin-panel__field" htmlFor={`${ID_PREFIX}-display`}>
        <span>Display name</span>
        <input
          id={`${ID_PREFIX}-display`}
          className="admin-panel__input"
          value={newProviderDisplay}
          onChange={(e) => setNewProviderDisplay(e.target.value)}
          placeholder="LiteLLM Gateway (governed)"
        />
      </label>
      <LiteLlmGatewayConfigFields
        draft={draft}
        onChange={setDraft}
        idPrefix={ID_PREFIX}
      />
      <LiteLlmGatewaySecretNotice
        secretRefConfigured={false}
        idPrefix={ID_PREFIX}
      />
      {error ? (
        <div className="admin-panel__error" role="alert">
          {error}
        </div>
      ) : null}
    </form>
  );
}
