import { ProviderApiKeyAuth } from "./ProviderApiKeyAuth";
import { ProviderBedrockPromptCaching } from "./ProviderBedrockPromptCaching";
import { ProviderCopilotAuth } from "./ProviderCopilotAuth";
import { ProviderGoogleAuth } from "./ProviderGoogleAuth";
import { ProviderLiteLlmGatewaySection } from "./ProviderLiteLlmGatewaySection";
import { ProviderRuntimeHints } from "./ProviderRuntimeHints";
import { LITELLM_GATEWAY_DRIVER } from "./litellmGatewayTypes";
import type { ProviderTabCtx } from "./types";

type ProviderAuthSectionProps = {
  ctx: ProviderTabCtx;
  provider: any;
};

export function ProviderAuthSection({
  ctx,
  provider: p,
}: ProviderAuthSectionProps) {
  return (
    <>
      <ProviderRuntimeHints provider={p} />

      {p.driver === "bedrock_api" ? (
        <ProviderBedrockPromptCaching ctx={ctx} provider={p} />
      ) : null}

      {p.driver === LITELLM_GATEWAY_DRIVER ? (
        <ProviderLiteLlmGatewaySection ctx={ctx} provider={p} />
      ) : null}

      {p.driver === "copilot_api" ? (
        <ProviderCopilotAuth ctx={ctx} provider={p} />
      ) : null}
      {p.driver === "gemini_api" ? (
        <ProviderGoogleAuth ctx={ctx} provider={p} />
      ) : null}
      {/* The governed gateway is excluded on purpose: its virtual key exists
          only as a Secret Reference, so no raw-key input may be offered. */}
      {p.driver !== "copilot_api" &&
      p.driver !== "gemini_api" &&
      p.driver !== "bedrock_api" &&
      p.driver !== LITELLM_GATEWAY_DRIVER ? (
        <ProviderApiKeyAuth ctx={ctx} provider={p} />
      ) : null}
    </>
  );
}
