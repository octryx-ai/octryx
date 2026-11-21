// Fixed readiness presentation for the governed LiteLLM gateway provider.
//
// `GET /chat/api/panel/providers` returns `readiness.status` and
// `readiness.reason` as closed codes (backend:
// services/provider/readiness.py plus services/model_gateway/litellm/readiness.py).
// Only those codes are rendered, each paired with copy written here. A remote
// gateway response body, endpoint, or auth header therefore has no path to the
// screen, and an unrecognized code degrades to a neutral "unrecognized" state
// instead of being echoed.

export const GATEWAY_READINESS_PREFIX = "litellm_gateway_";

export type GatewayReadinessTone = "ready" | "blocked" | "unknown";

export type ProviderReadinessInput = {
  status?: unknown;
  reason?: unknown;
  runtime_attempt_allowed?: unknown;
};

export type PresentedReadiness = {
  code: string;
  statusCode: string;
  statusLabel: string;
  label: string;
  tone: GatewayReadinessTone;
  recognized: boolean;
  runtimeAttemptAllowed: boolean;
};

const READINESS_STATUS_LABELS: Record<string, string> = {
  ready: "Ready",
  degraded: "Degraded",
  unknown: "Unknown",
  unavailable: "Unavailable",
  needs_configuration: "Needs configuration",
};

const READINESS_STATUS_TONES: Record<string, GatewayReadinessTone> = {
  ready: "ready",
  degraded: "unknown",
  unknown: "unknown",
  unavailable: "blocked",
  needs_configuration: "blocked",
};

// Gateway-specific `needs_configuration` reasons. Keys are the full backend
// code, including the `litellm_gateway_` prefix the backend adds.
export const GATEWAY_READINESS_REASON_LABELS: Record<string, string> = {
  litellm_gateway_alias_catalog_missing:
    "The provider config has no litellm_gateway section yet.",
  litellm_gateway_alias_catalog_contains_credential_material:
    "The gateway config carries a credential-looking key. Keys belong behind the Secret Reference only.",
  litellm_gateway_alias_catalog_has_no_admitted_alias:
    "No alias in the catalog passes admission. Each alias needs a model group, context limit, data policy class and cost contract.",
  litellm_gateway_virtual_key_secret_ref_not_configured:
    "The gateway virtual key is not linked as a Secret Reference yet.",
  litellm_gateway_endpoint_not_configured: "No gateway base URL is configured.",
  litellm_gateway_endpoint_unparsable: "The gateway base URL cannot be parsed.",
  litellm_gateway_endpoint_scheme_not_supported:
    "The base URL scheme is not supported. Use https, or http on loopback only.",
  litellm_gateway_endpoint_insecure_off_loopback:
    "Plain http is admitted on loopback only. Use https for a remote gateway.",
  litellm_gateway_endpoint_userinfo_present:
    "The base URL carries userinfo. Remove any user:password part.",
  litellm_gateway_endpoint_query_present:
    "The base URL carries a query string. Configure the bare origin.",
  litellm_gateway_endpoint_fragment_present:
    "The base URL carries a fragment. Configure the bare origin.",
  litellm_gateway_endpoint_unexpected_path:
    "The base URL path is not admitted. Use the origin or the pinned /v1 prefix.",
  litellm_gateway_endpoint_host_missing: "The base URL has no host.",
  litellm_gateway_endpoint_host_allowlist_not_configured:
    "The gateway host allowlist is empty. Declare at least one bare host.",
  litellm_gateway_endpoint_host_allowlist_invalid:
    "An allowlist entry is not a bare host. Drop any scheme, port, path or wildcard.",
  litellm_gateway_endpoint_host_not_allowlisted:
    "The base URL host is not on the gateway host allowlist.",
  litellm_gateway_probe_contract_missing:
    "The pinned probe contract is missing from the gateway config.",
  litellm_gateway_probe_contract_path_not_pinned:
    "The probe models path is not one of the pinned paths.",
  litellm_gateway_probe_contract_response_shape_not_pinned:
    "The probe response shape is not one of the pinned shapes.",
  litellm_gateway_probe_contract_model_group_field_not_pinned:
    "The probe model group field is not one of the pinned fields.",
  // Transport trust store and governed proxy. Ambient HTTP(S)_PROXY and
  // SSL_CERT_* variables are never used, so both are explicit configuration.
  litellm_gateway_tls_contract_missing:
    "The gateway config has no tls section. Declare private_ca_bundle, public_ca_bundle, plaintext_loopback or plaintext_cluster_internal.",
  litellm_gateway_tls_mode_unknown:
    "The tls mode is not one of private_ca_bundle, public_ca_bundle, plaintext_loopback or plaintext_cluster_internal.",
  litellm_gateway_tls_mode_conflicts_with_endpoint_scheme:
    "The tls mode does not match the base URL scheme. Use plaintext_loopback (loopback) or plaintext_cluster_internal (cluster Service) for http, a CA bundle for https.",
  litellm_gateway_tls_plaintext_not_permitted_off_loopback:
    "Plaintext trust is admitted on loopback only.",
  litellm_gateway_tls_plaintext_cluster_internal_host_not_cluster_service:
    "plaintext_cluster_internal is admitted only for a fully qualified <service>.<namespace>.svc.cluster.local host.",
  litellm_gateway_tls_node_encryption_not_attested:
    "plaintext_cluster_internal needs node_encryption set to wireguard: the operator's attestation that node-to-node traffic is encrypted.",
  litellm_gateway_tls_attestation_reference_missing:
    "plaintext_cluster_internal needs the governance record (attestation_reference) that attests the node encryption.",
  litellm_gateway_tls_attested_on_invalid:
    "The node-encryption attestation date (attested_on) must be an ISO date.",
  litellm_gateway_tls_ca_bundle_path_not_configured:
    "The CA bundle path is missing. Both bundle modes need an explicit absolute path; no bundle is inherited from the environment or from a library.",
  litellm_gateway_tls_ca_bundle_path_not_absolute:
    "The CA bundle path must be absolute.",
  litellm_gateway_tls_ca_bundle_not_a_file:
    "No readable file exists at the configured CA bundle path.",
  litellm_gateway_tls_ca_bundle_not_readable:
    "The CA bundle file cannot be read by the backend process.",
  litellm_gateway_tls_ca_bundle_too_large:
    "The CA bundle file is larger than a certificate bundle should be.",
  litellm_gateway_tls_ca_bundle_no_certificate:
    "The CA bundle contains no certificate.",
  litellm_gateway_tls_ca_bundle_contains_private_key:
    "The CA bundle contains a private key. A trust store must not carry credential material.",
  litellm_gateway_tls_ca_bundle_not_loadable:
    "The CA bundle could not be loaded as a trust store.",
  litellm_gateway_tls_ca_bundle_material_changed:
    "The CA bundle file no longer matches the trust material that was validated. Re-save the provider after rotating the bundle.",
  litellm_gateway_proxy_contract_malformed:
    "The proxy section is malformed. Use mode direct or governed_proxy.",
  litellm_gateway_proxy_mode_unknown:
    "The proxy mode is not direct or governed_proxy.",
  litellm_gateway_proxy_url_not_configured:
    "The governed proxy URL is missing.",
  litellm_gateway_proxy_url_unparsable:
    "The governed proxy URL cannot be parsed.",
  litellm_gateway_proxy_scheme_not_supported:
    "The proxy scheme is not supported. Use http or https.",
  litellm_gateway_proxy_userinfo_present:
    "The proxy URL carries credentials. Proxy credentials are not configurable here.",
  litellm_gateway_proxy_query_present:
    "The proxy URL carries a query string. Configure the bare origin.",
  litellm_gateway_proxy_fragment_present:
    "The proxy URL carries a fragment. Configure the bare origin.",
  litellm_gateway_proxy_unexpected_path:
    "The proxy URL carries a path. Configure the bare origin.",
  litellm_gateway_proxy_host_missing: "The proxy URL has no host.",
  litellm_gateway_proxy_host_allowlist_not_configured:
    "The proxy host allowlist is empty. Declare at least one bare host.",
  litellm_gateway_proxy_host_allowlist_invalid:
    "A proxy allowlist entry is not a bare host.",
  litellm_gateway_proxy_host_not_allowlisted:
    "The proxy host is not on the proxy host allowlist.",
  litellm_gateway_proxy_plaintext_requires_tls_endpoint:
    "A plaintext proxy hop is admitted only when the gateway leg is https.",
  litellm_gateway_proxy_not_permitted_with_cluster_internal_plaintext:
    "plaintext_cluster_internal is direct only. Remove the governed proxy or use a CA bundle mode over https.",
  litellm_gateway_proxy_tls_trust_not_configured:
    "An https proxy needs a validated CA bundle to verify the proxy certificate against. Use a CA bundle TLS mode, or an http proxy with an https gateway.",
  // Content-logging posture. The gateway must retain neither prompts nor
  // credentials, and the posture must say how it was verified.
  litellm_gateway_content_logging_contract_missing:
    "The gateway config has no content_logging section. Declare the retention posture and its attestation.",
  litellm_gateway_content_logging_mode_not_admitted:
    "Only the no_content_retention posture is admitted.",
  litellm_gateway_content_logging_prompt_retention_not_disabled:
    "Prompt retention must be disabled.",
  litellm_gateway_content_logging_response_retention_not_disabled:
    "Response retention must be disabled.",
  litellm_gateway_content_logging_header_retention_not_disabled:
    "Request header retention must be disabled: the headers carry the gateway virtual key.",
  litellm_gateway_content_logging_key_metadata_retention_not_disabled:
    "Key metadata retention must be disabled, or retained_by_internal_platform_gateway for an internal platform-operated gateway's spend logs.",
  litellm_gateway_content_logging_key_metadata_retention_requires_no_callbacks:
    "retained_by_internal_platform_gateway is admitted only with empty success and failure callback lists.",
  litellm_gateway_content_logging_callbacks_malformed:
    "The success and failure callback lists must both be declared as lists.",
  litellm_gateway_content_logging_callback_may_retain_content:
    "A declared callback can retain prompts or responses, so it is not admitted.",
  litellm_gateway_content_logging_attestation_reference_missing:
    "The posture needs the governance record that attests it.",
  litellm_gateway_content_logging_attested_on_invalid:
    "The attestation date must be an ISO date.",
  litellm_gateway_content_logging_verification_source_unknown:
    "The posture must state whether it was verified against the declared or the live gateway configuration.",
};

// Reasons any provider can report, gateway or not.
export const PROVIDER_READINESS_REASON_LABELS: Record<string, string> = {
  provider_missing: "The provider row is gone.",
  provider_inactive:
    "The provider is inactive, so no runtime attempt is allowed.",
  driver_unsupported:
    "This provider names no supported driver, so it cannot run. Delete the row or create one on a supported driver.",
  endpoint_url_not_configured: "This driver needs an endpoint URL.",
  api_key_not_configured:
    "No credential is stored behind the Secret Reference.",
  aws_credentials_not_configured: "Static AWS credentials are not configured.",
  health_check_ok: "The last health check succeeded.",
  no_models: "No models are registered for this provider.",
  stale_cache: "The model cache is stale.",
  health_auth_denied: "The last health check was denied by authentication.",
  health_error: "The last health check reported an error.",
  health_failed: "The last health check failed.",
  health_model_sync_failed: "The last model sync failed.",
  health_provider_unavailable: "The provider reported itself unavailable.",
  health_stopped: "The runtime is stopped.",
  health_unavailable: "The provider is unavailable.",
  health_validation_failed: "The last validation failed.",
  health_status_unrecognized: "The stored health status is not a known value.",
  health_unchecked: "No health check has run yet.",
  health_not_required: "This driver needs no health check.",
};

const SAFE_READINESS_CODE = /^[a-z0-9_]{1,80}$/;

/** Keep only a closed-code-shaped string; anything else becomes "unrecognized". */
export function safeReadinessCode(value: unknown): string {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase();
  return SAFE_READINESS_CODE.test(normalized) ? normalized : "unrecognized";
}

export function presentProviderReadiness(
  readiness: ProviderReadinessInput | null | undefined,
): PresentedReadiness {
  const statusCode = safeReadinessCode(readiness?.status);
  const code = safeReadinessCode(readiness?.reason);
  const label =
    GATEWAY_READINESS_REASON_LABELS[code] ??
    PROVIDER_READINESS_REASON_LABELS[code] ??
    "";
  return {
    code,
    statusCode,
    statusLabel: READINESS_STATUS_LABELS[statusCode] ?? "Unrecognized",
    label: label || "This readiness code has no admin description yet.",
    tone: READINESS_STATUS_TONES[statusCode] ?? "unknown",
    recognized: Boolean(label) && statusCode in READINESS_STATUS_LABELS,
    runtimeAttemptAllowed: readiness?.runtime_attempt_allowed === true,
  };
}

export function isGatewayReadinessCode(code: string): boolean {
  return code.startsWith(GATEWAY_READINESS_PREFIX);
}
