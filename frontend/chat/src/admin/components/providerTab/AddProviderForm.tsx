import { useState, type ReactNode } from "react";

import { FormSection } from "../../../layout/FormSection";
import { SidePanel } from "../../../layout/SidePanel";
import { LiteLlmGatewayAddForm, type GatewayFormState } from "./LiteLlmGatewayAddForm";
import { ProviderTypeSelect } from "./ProviderTypeSelect";
import { LITELLM_GATEWAY_DRIVER } from "./litellmGatewayTypes";
import { PROVIDER_CREATE_ENDPOINT_CHOICES } from "./providerCreateChoices";
import type { ProviderTabCtx } from "./types";

type AddProviderFormProps = {
  ctx: ProviderTabCtx;
};

// "Add provider": a side panel over the dimmed provider list, every field with its
// label, Cancel and the primary action at the bottom right. The forms submit; the footer button submits
// them through `form=`.
export const ADD_PROVIDER_FORM_ID = "add-provider-form";

function Labelled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="admin-panel__field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function AddProviderForm({ ctx }: AddProviderFormProps) {
  const { newProviderDriver, providerFormLoading, setShowAddProvider, showAddProvider } = ctx;
  const [gateway, setGateway] = useState<GatewayFormState>({ saving: false, submittable: false });

  if (!showAddProvider) {
    return null;
  }

  const close = () => setShowAddProvider(false);
  // The governed gateway has its own form: its fields, validation codes and
  // submitted payload are a closed contract, and it must never offer the
  // credential inputs the generic form below carries.
  const isGateway = newProviderDriver === LITELLM_GATEWAY_DRIVER;
  const busy = isGateway ? gateway.saving : providerFormLoading;
  const footer = (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={close} data-testid="provider-add-cancel">
        Cancel
      </button>
      <button
        type="submit"
        form={ADD_PROVIDER_FORM_ID}
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={busy || (isGateway && !gateway.submittable)}
        data-testid="provider-add-submit"
      >
        {busy ? "Adding…" : isGateway ? "Add LiteLLM gateway" : "Add provider"}
      </button>
    </>
  );

  return (
    <SidePanel title="Add provider" onClose={close} footer={footer} testId="provider-add-panel">
      {isGateway ? (
        <LiteLlmGatewayAddForm ctx={ctx} formId={ADD_PROVIDER_FORM_ID} onStateChange={setGateway} />
      ) : (
        <GenericProviderForm ctx={ctx} />
      )}
    </SidePanel>
  );
}

// Every other provider type: the provider fields and its access section, submitted through the footer button.
function GenericProviderForm({ ctx }: AddProviderFormProps) {
  const { handleAddProvider, newProviderDriver, providerFormError } = ctx;
  return (
    <form id={ADD_PROVIDER_FORM_ID} className="provider-form" onSubmit={(e) => void handleAddProvider(e)}>
      <ProviderFields ctx={ctx} />
      {newProviderDriver === "bedrock_api" ? (
        <BedrockAccessSection ctx={ctx} />
      ) : newProviderDriver === "gemini_api" ? (
        <GoogleAccessSection ctx={ctx} />
      ) : newProviderDriver !== "ollama" && newProviderDriver !== "copilot_api" ? (
        <ApiKeyAccessSection ctx={ctx} />
      ) : null}
      {providerFormError ? <div className="admin-panel__error" role="alert">{providerFormError}</div> : null}
    </form>
  );
}

// Type, display name and, where the type takes one, the endpoint.
function ProviderFields({ ctx }: AddProviderFormProps) {
  const { newProviderDisplay, newProviderEndpointUrl, newProviderDriver, setNewProviderDisplay, setNewProviderEndpointUrl, setNewProviderDriver } = ctx;
  return (
    <FormSection title="Provider">
      <ProviderTypeSelect value={newProviderDriver} onChange={setNewProviderDriver} />
      <Labelled label="Display name">
        <input
          className="admin-panel__input"
          placeholder="e.g. Claude (team)"
          value={newProviderDisplay}
          onChange={(e) => setNewProviderDisplay(e.target.value)}
        />
      </Labelled>
      {PROVIDER_CREATE_ENDPOINT_CHOICES.includes(newProviderDriver) ? (
        <Labelled label={newProviderDriver === "ollama" ? "Ollama URL" : newProviderDriver === "copilot_api" ? "Copilot API base URL (optional)" : "API base URL"}>
          <input
            className="admin-panel__input"
            placeholder={
              newProviderDriver === "ollama"
                ? "e.g. http://localhost:11434 or http://ollama:11434"
                : newProviderDriver === "copilot_api"
                  ? "e.g. https://api.individual.githubcopilot.com"
                  : "e.g. http://localhost:8001/v1"
            }
            value={newProviderEndpointUrl}
            onChange={(e) => setNewProviderEndpointUrl(e.target.value)}
          />
        </Labelled>
      ) : null}
    </FormSection>
  );
}

function BedrockAccessSection({ ctx }: AddProviderFormProps) {
  const {
    newProviderArn, newProviderKey, newProviderRegion, newProviderSecretKey, newProviderSessionToken,
    setNewProviderArn, setNewProviderKey, setNewProviderRegion, setNewProviderSecretKey, setNewProviderSessionToken,
  } = ctx;
  return (
    <FormSection title="Access">
      <Labelled label="AWS region">
        <input
          className="admin-panel__input"
          placeholder="e.g. us-east-1"
          value={newProviderRegion}
          onChange={(e) => setNewProviderRegion(e.target.value)}
        />
      </Labelled>
      <Labelled label="IAM role ARN (optional)">
        <input className="admin-panel__input" value={newProviderArn} onChange={(e) => setNewProviderArn(e.target.value)} />
      </Labelled>
      <Labelled label="AWS access key ID (optional for local dev)">
        <input className="admin-panel__input" value={newProviderKey} onChange={(e) => setNewProviderKey(e.target.value)} />
      </Labelled>
      <Labelled label="AWS secret access key">
        <input
          className="admin-panel__input"
          type="password"
          value={newProviderSecretKey}
          onChange={(e) => setNewProviderSecretKey(e.target.value)}
        />
      </Labelled>
      <Labelled label="AWS session token (optional)">
        <input
          className="admin-panel__input"
          type="password"
          value={newProviderSessionToken}
          onChange={(e) => setNewProviderSessionToken(e.target.value)}
        />
      </Labelled>
    </FormSection>
  );
}

function GoogleAccessSection({ ctx }: AddProviderFormProps) {
  const {
    newGoogleClientId, newGoogleClientSecret, newGoogleCloudProject, newProviderAuthMode, newProviderKey,
    setNewGoogleClientId, setNewGoogleClientSecret, setNewGoogleCloudProject, setNewProviderAuthMode, setNewProviderKey,
  } = ctx;
  return (
    <FormSection title="Access">
      <Labelled label="Google auth mode">
        <select className="admin-panel__input" value={newProviderAuthMode} onChange={(e) => setNewProviderAuthMode(e.target.value)}>
          <option value="oauth">Google login</option>
          <option value="api_key">Gemini API key</option>
        </select>
      </Labelled>
      {newProviderAuthMode === "oauth" ? (
        <>
          <Labelled label="Google OAuth client ID">
            <input className="admin-panel__input" value={newGoogleClientId} onChange={(e) => setNewGoogleClientId(e.target.value)} />
          </Labelled>
          <Labelled label="Google OAuth client secret">
            <input
              className="admin-panel__input"
              type="password"
              value={newGoogleClientSecret}
              onChange={(e) => setNewGoogleClientSecret(e.target.value)}
            />
          </Labelled>
          <Labelled label="Google Cloud project">
            <input className="admin-panel__input" value={newGoogleCloudProject} onChange={(e) => setNewGoogleCloudProject(e.target.value)} />
          </Labelled>
        </>
      ) : (
        <Labelled label="Gemini API key">
          <input className="admin-panel__input" type="password" value={newProviderKey} onChange={(e) => setNewProviderKey(e.target.value)} />
        </Labelled>
      )}
    </FormSection>
  );
}

function ApiKeyAccessSection({ ctx }: AddProviderFormProps) {
  const { newProviderKey, newProviderDriver, setNewProviderKey } = ctx;
  return (
    <FormSection title="Access">
      <Labelled label={newProviderDriver === "openai_compatible" ? "API key (optional for local gateways)" : "API key"}>
        <input className="admin-panel__input" type="password" value={newProviderKey} onChange={(e) => setNewProviderKey(e.target.value)} />
      </Labelled>
    </FormSection>
  );
}
