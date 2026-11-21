import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";
import type { ProviderDraft } from "./useAdminProviderManagement.types";

const DEFAULT_PROVIDER_DRAFT: ProviderDraft = {
  auth_mode: "api_key",
  google_oauth_client_id: "",
  google_oauth_client_secret: "",
  google_cloud_project: "",
  bedrock_prompt_cache_enabled: "false",
  bedrock_prompt_cache_ttl: "5m",
  bedrock_prompt_cache_min_tokens: "",
  aws_access_key_id: "",
  aws_secret_access_key: "",
  aws_session_token: "",
};

export function normalizeProviderDraft(draft?: ProviderDraft): ProviderDraft {
  return {
    ...DEFAULT_PROVIDER_DRAFT,
    ...(draft || {}),
  };
}

export function buildProviderDraftFromProvider(provider: AdminProvider): ProviderDraft {
  const promptCaching = getBedrockPromptCachingConfig(provider);
  const promptCachingMinTokens =
    typeof promptCaching.min_tokens === "number" &&
    Number.isFinite(promptCaching.min_tokens)
      ? String(promptCaching.min_tokens)
      : "";

  return {
    auth_mode: provider.auth_mode || "api_key",
    google_oauth_client_id: provider.google_oauth_client_id || "",
    google_oauth_client_secret: "",
    google_cloud_project: provider.google_cloud_project || "",
    bedrock_prompt_cache_enabled:
      promptCaching.enabled === true ? "true" : "false",
    bedrock_prompt_cache_ttl:
      typeof promptCaching.ttl === "string" && promptCaching.ttl.trim()
        ? promptCaching.ttl.trim()
        : "5m",
    bedrock_prompt_cache_min_tokens: promptCachingMinTokens,
    aws_access_key_id: "",
    aws_secret_access_key: "",
    aws_session_token: "",
  };
}

function getBedrockPromptCachingConfig(provider: AdminProvider) {
  const raw = provider.config_json?.prompt_caching;
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : {};
}

export function buildBedrockProviderConfigUpdate(
  provider: AdminProvider,
  draft: ProviderDraft,
) {
  const nextConfig: Record<string, unknown> = {
    ...(provider.config_json || {}),
  };
  const minTokensText = draft.bedrock_prompt_cache_min_tokens.trim();
  const minTokens = minTokensText ? Number(minTokensText) : null;
  const promptCaching: Record<string, unknown> = {
    enabled: draft.bedrock_prompt_cache_enabled === "true",
    ttl: draft.bedrock_prompt_cache_ttl.trim() || "5m",
    cache_system: true,
    cache_tools: true,
  };

  if (minTokens != null && Number.isFinite(minTokens) && minTokens > 0) {
    promptCaching.min_tokens = Math.floor(minTokens);
  }

  nextConfig.prompt_caching = promptCaching;

  return {
    config_json: nextConfig,
    auth_mode:
      draft.aws_access_key_id.trim() && draft.aws_secret_access_key.trim()
        ? "aws_credentials"
        : undefined,
    aws_access_key_id: draft.aws_access_key_id.trim() || undefined,
    aws_secret_access_key: draft.aws_secret_access_key.trim() || undefined,
    aws_session_token: draft.aws_session_token.trim() || undefined,
  };
}

export function buildBedrockDraftFromUpdatedProvider(
  updated: AdminProvider,
  draft: ProviderDraft,
) {
  const promptCaching = getBedrockPromptCachingConfig(updated);
  return {
    ...draft,
    bedrock_prompt_cache_enabled:
      promptCaching.enabled === true ? "true" : "false",
    bedrock_prompt_cache_ttl:
      typeof promptCaching.ttl === "string" && promptCaching.ttl.trim()
        ? promptCaching.ttl.trim()
        : "5m",
    bedrock_prompt_cache_min_tokens:
      typeof promptCaching.min_tokens === "number" &&
      Number.isFinite(promptCaching.min_tokens)
        ? String(promptCaching.min_tokens)
        : "",
    aws_access_key_id: "",
    aws_secret_access_key: "",
    aws_session_token: "",
  };
}
