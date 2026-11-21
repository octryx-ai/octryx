// The Admin provider create catalog.
//
// `value` is the exact backend driver id (`backend/app/agent/providers/provider_registry.py`
// DRIVER_SPECS) and is submitted as the create payload's `driver`; the backend refuses
// any other value with a bounded 400 (`services/provider/driver_policy.py`).

export type ProviderCreateChoice = {
  value: string;
  label: string;
};

export const PROVIDER_CREATE_CHOICES: readonly ProviderCreateChoice[] = [
  { value: "openrouter_api", label: "OpenRouter" },
  { value: "bedrock_api", label: "AWS Bedrock" },
  { value: "copilot_api", label: "GitHub Copilot" },
  { value: "gemini_api", label: "Google Gemini (API / Cloud)" },
  { value: "ollama", label: "Ollama / Local Models" },
  { value: "openai_compatible", label: "OpenAI-Compatible API" },
  { value: "litellm_gateway", label: "LiteLLM Gateway (governed)" },
];

/** The create choices that carry an endpoint/base-URL input. */
export const PROVIDER_CREATE_ENDPOINT_CHOICES: readonly string[] = [
  "ollama",
  "openai_compatible",
  "copilot_api",
];

export const DEFAULT_PROVIDER_CREATE_DRIVER = "openrouter_api";

export function providerCreateChoiceLabel(driver: string): string {
  return PROVIDER_CREATE_CHOICES.find((choice) => choice.value === driver)?.label ?? driver;
}
