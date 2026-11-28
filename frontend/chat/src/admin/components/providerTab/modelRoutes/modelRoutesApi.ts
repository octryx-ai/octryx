import { readJson } from "../../../utils/adminPanelHelpers";

export type ModelRoute = {
  alias: string;
  provider_type: string;
  model: string;
  settings: Record<string, string>;
  data_policy_class: string | null;
  context_limit: number | null;
  input_per_million_usd: number | null;
  output_per_million_usd: number | null;
  tools: boolean;
  state: "ok" | "needs_configuration";
  problem: string;
};

export type ProviderTypeSpec = { fields: string[]; required: string[] };

export type ModelRoutesPayload = {
  routes: ModelRoute[];
  provider_types: Record<string, ProviderTypeSpec>;
  data_policy_classes: string[];
};

export type ModelRouteDraft = {
  alias: string;
  provider_type: string;
  model: string;
  credentials: Record<string, string>;
  data_policy_class: string;
  context_limit: string;
  input_per_million_usd: string;
  output_per_million_usd: string;
  tools: boolean;
};

export type RouteTestResult = { state: "ok"; latency_ms: number } | { state: "error"; error: string; reason: string };

const BASE = "/admin/chat/api/panel/model-routes";

export const PROVIDER_TYPE_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  bedrock: "AWS Bedrock",
  azure: "Azure OpenAI",
  gemini: "Google Gemini",
  openrouter: "OpenRouter",
  ollama: "Ollama",
  openai_compatible: "OpenAI-compatible",
};

export const FIELD_LABELS: Record<string, string> = {
  api_key: "API key",
  api_base: "Base URL",
  api_version: "API version",
  aws_region_name: "AWS region",
  aws_access_key_id: "AWS access key ID",
  aws_secret_access_key: "AWS secret access key",
  aws_session_token: "AWS session token",
};

// Credentials are write-only: an edit shows them empty and an empty field keeps the stored value.
export const SECRET_FIELDS = new Set(["api_key", "aws_access_key_id", "aws_secret_access_key", "aws_session_token"]);

export function emptyDraft(defaults: { providerType: string; dataClass: string }): ModelRouteDraft {
  return {
    alias: "", provider_type: defaults.providerType, model: "", credentials: {}, data_policy_class: defaults.dataClass,
    context_limit: "200000", input_per_million_usd: "", output_per_million_usd: "", tools: true,
  };
}

export function draftFromRoute(route: ModelRoute): ModelRouteDraft {
  return {
    alias: route.alias, provider_type: route.provider_type, model: route.model, credentials: { ...route.settings },
    data_policy_class: route.data_policy_class ?? "", context_limit: String(route.context_limit ?? ""),
    input_per_million_usd: String(route.input_per_million_usd ?? ""),
    output_per_million_usd: String(route.output_per_million_usd ?? ""), tools: route.tools,
  };
}

function body(draft: ModelRouteDraft): string {
  return JSON.stringify({
    ...draft,
    context_limit: Number(draft.context_limit),
    input_per_million_usd: Number(draft.input_per_million_usd),
    output_per_million_usd: Number(draft.output_per_million_usd),
  });
}

export const loadModelRoutes = () => readJson<ModelRoutesPayload>(BASE);

export const saveModelRoute = (draft: ModelRouteDraft, editing: boolean) =>
  readJson<ModelRoute>(editing ? `${BASE}/${encodeURIComponent(draft.alias)}` : BASE, {
    method: editing ? "PUT" : "POST", body: body(draft),
  });

export const deleteModelRoute = (alias: string) =>
  readJson<{ deleted: string }>(`${BASE}/${encodeURIComponent(alias)}`, { method: "DELETE" });

export const testModelRoute = (alias: string) =>
  readJson<RouteTestResult>(`${BASE}/${encodeURIComponent(alias)}/test`, { method: "POST" });
