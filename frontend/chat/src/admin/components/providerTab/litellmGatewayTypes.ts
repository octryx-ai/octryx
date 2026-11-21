// LiteLLM gateway contract constants, closed enums, draft/payload types and form codes.

// Two hard rules live here:
//   1. No credential field. The gateway virtual key is reachable only through
//      LLMProvider.api_key_secret_ref, and no canonical Admin API accepts an
//      existing secret reference, so the UI submits neither a key nor a ref.
//   2. Every closed enum is the backend's closed enum. A value outside it is a
//      form error, never a request.

export const LITELLM_GATEWAY_DRIVER = "litellm_gateway";
export const LITELLM_GATEWAY_CONFIG_KEY = "litellm_gateway";

export const GATEWAY_PROBE_PATHS = ["/models", "/model/info"] as const;
export const GATEWAY_PROBE_RESPONSE_SHAPES = ["openai_model_list"] as const;
export const GATEWAY_PROBE_MODEL_GROUP_FIELDS = ["id", "model_name"] as const;
export const GATEWAY_DATA_POLICY_CLASSES = [
  "public",
  "internal",
  "confidential",
  "restricted",
] as const;
export const GATEWAY_CAPABILITIES = [
  "tools",
  "structured_output",
  "reasoning",
  "vision",
] as const;
export const GATEWAY_COST_SOURCES = [
  "catalog_pricing",
  "gateway_reported",
  "governed_free",
] as const;

export const GATEWAY_MIN_REQUEST_TIMEOUT_SECONDS = 5;
export const GATEWAY_MAX_REQUEST_TIMEOUT_SECONDS = 600;

export type GatewayProbePath = (typeof GATEWAY_PROBE_PATHS)[number];
export type GatewayProbeResponseShape =
  (typeof GATEWAY_PROBE_RESPONSE_SHAPES)[number];
export type GatewayProbeModelGroupField =
  (typeof GATEWAY_PROBE_MODEL_GROUP_FIELDS)[number];
export type GatewayDataPolicyClass =
  (typeof GATEWAY_DATA_POLICY_CLASSES)[number];
export type GatewayCapability = (typeof GATEWAY_CAPABILITIES)[number];
export type GatewayCostSource = (typeof GATEWAY_COST_SOURCES)[number];

export type GatewayAliasCostDraft = {
  source: GatewayCostSource;
  inputPerMillionUsd: string;
  outputPerMillionUsd: string;
  contractReference: string;
};

export type GatewayAliasDraft = {
  alias: string;
  modelGroup: string;
  contextLimit: string;
  dataPolicyClass: GatewayDataPolicyClass;
  capabilities: Record<GatewayCapability, boolean>;
  cost: GatewayAliasCostDraft;
  /** "Approved for sensitive data": content category ids. */
  approvedDataCategories: string[];
  /**
   * The stored alias keys this form does not render (display name, served model ids,
   * cache prices, …). They ride along with the row, so a save (or a rename) keeps them.
   */
  preserved?: GatewayAliasPreserved;
  /**
   * True for an alias read from the stored catalog. Its governed fields (data class, capabilities, approved for,
   * cost) are edited in Runtime → Model catalog; only a new alias declares them here.
   */
  stored?: boolean;
};

export type GatewayAliasPreserved = {
  entry: Record<string, unknown>;
  cost: Record<string, unknown>;
  costSource: GatewayCostSource;
};

export type GatewayDraft = {
  displayName: string;
  endpointUrl: string;
  hostAllowlist: string;
  probeModelsPath: GatewayProbePath;
  probeResponseShape: GatewayProbeResponseShape;
  probeModelGroupField: GatewayProbeModelGroupField;
  requestTimeoutSeconds: string;
  aliases: GatewayAliasDraft[];
};

export type GatewayAliasCost = {
  source: GatewayCostSource;
  input_per_million_usd?: number;
  output_per_million_usd?: number;
  contract_reference?: string;
};

export type GatewayAliasEntry = {
  model_group: string;
  context_limit: number;
  data_policy_class: GatewayDataPolicyClass;
  capabilities: Record<GatewayCapability, boolean>;
  cost: GatewayAliasCost;
  approved_data_categories?: string[];
};

export type GatewayConfigSection = {
  host_allowlist: string[];
  probe_contract: {
    models_path: GatewayProbePath;
    response_shape: GatewayProbeResponseShape;
    model_group_field: GatewayProbeModelGroupField;
  };
  aliases: Record<string, GatewayAliasEntry>;
  request_timeout_seconds?: number;
};

export type GatewayCreatePayload = {
  driver: typeof LITELLM_GATEWAY_DRIVER;
  display_name: string;
  endpoint_url: string;
  config_json: Record<string, unknown>;
  is_global: true;
};

export type GatewayUpdatePayload = {
  display_name: string;
  endpoint_url: string;
  config_json: Record<string, unknown>;
};

// Form codes. The alias/endpoint/probe codes are the backend's own admission
// denial codes so an operator reads one vocabulary on both sides. The two
// `form_` codes have no backend twin: the catalog is a mapping server-side, so a
// duplicate alias would silently collapse, and a blank row would vanish.
export const GATEWAY_FORM_CODE_ALIAS_DECLARED_TWICE =
  "form_alias_declared_twice";
export const GATEWAY_FORM_CODE_TIMEOUT_OUT_OF_RANGE =
  "form_request_timeout_seconds_out_of_range";
