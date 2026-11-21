// Credential summary shown in a provider row. It only reads stored state flags
// (never a key value). Bedrock (`bedrock_api`) authenticates through AWS: without
// static keys it uses the pod's IAM role or the configured AWS profile, so "No key"
// would be misleading there.

type ProviderAuthSource = {
  name?: string | null;
  driver?: string | null;
  runtime_kind?: string | null;
  endpoint_url?: string | null;
  auth_mode?: string | null;
  auth_login?: string | null;
  auth_name?: string | null;
  auth_host?: string | null;
  google_cloud_project?: string | null;
  has_api_key?: boolean | null;
  aws_static_credentials_configured?: boolean | null;
};

export const BEDROCK_DRIVER = "bedrock_api";

export function providerAuthLabel(provider: ProviderAuthSource): string {
  if (provider.driver === BEDROCK_DRIVER) {
    if (provider.auth_mode === "aws_credentials") {
      return provider.aws_static_credentials_configured
        ? "AWS access keys configured"
        : "AWS access keys missing";
    }
    return "AWS IAM / profile";
  }
  if (provider.driver === "copilot_api" && provider.auth_login) {
    return `${provider.auth_name || provider.auth_login} · @${provider.auth_login} · ${provider.auth_host || "https://github.com"}`;
  }
  if (
    provider.driver === "gemini_api" &&
    provider.auth_mode === "oauth" &&
    provider.auth_login
  ) {
    return `${provider.auth_name || provider.auth_login} · ${provider.google_cloud_project || "no project"}`;
  }
  if (provider.runtime_kind === "local" && provider.endpoint_url) {
    return "local runtime";
  }
  return provider.has_api_key ? "Key configured" : "No key";
}
