import { useState } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { LiteLlmGatewayAddForm, type GatewayFormState } from "./LiteLlmGatewayAddForm";
import type { ProviderTabCtx } from "./types";

type AddProviderFormProps = {
  ctx: ProviderTabCtx;
};

// "Add provider": a side panel over the dimmed provider list, Cancel and the primary action at the bottom right.
// The footer button submits the gateway form through `form=`.
export const ADD_PROVIDER_FORM_ID = "add-provider-form";

export function AddProviderForm({ ctx }: AddProviderFormProps) {
  const { setShowAddProvider, showAddProvider } = ctx;
  const [gateway, setGateway] = useState<GatewayFormState>({ saving: false, submittable: false });

  if (!showAddProvider) {
    return null;
  }

  const close = () => setShowAddProvider(false);
  const footer = (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={close} data-testid="provider-add-cancel">
        Cancel
      </button>
      <button
        type="submit"
        form={ADD_PROVIDER_FORM_ID}
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={gateway.saving || !gateway.submittable}
        data-testid="provider-add-submit"
      >
        {gateway.saving ? "Adding…" : "Add LiteLLM gateway"}
      </button>
    </>
  );

  return (
    <SidePanel title="Add provider" onClose={close} footer={footer} testId="provider-add-panel">
      <LiteLlmGatewayAddForm ctx={ctx} formId={ADD_PROVIDER_FORM_ID} onStateChange={setGateway} />
    </SidePanel>
  );
}
