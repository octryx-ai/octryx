// The governed LiteLLM gateway in words, never raw codes (health_check_ok, openai_model_list,
// model_name). Pure: no React. Values sent to the server stay the contract's codes; only what is
// shown changes.

const PROBE_PATH_LABELS: Record<string, string> = {
  "/models": "/models (OpenAI-compatible list)",
  "/model/info": "/model/info (LiteLLM model info)",
};
const RESPONSE_SHAPE_LABELS: Record<string, string> = { openai_model_list: "OpenAI model list" };
const MODEL_GROUP_FIELD_LABELS: Record<string, string> = { id: "Model ID", model_name: "Model name" };
const POLICY_CLASS_LABELS: Record<string, string> = {
  public: "Public",
  internal: "Internal",
  confidential: "Confidential",
  restricted: "Restricted",
};
const COST_SOURCE_LABELS: Record<string, string> = {
  catalog_pricing: "Priced here",
  gateway_reported: "Priced by the gateway",
  governed_free: "Free, under a governance record",
};

const CODE_TEXTS: Record<string, string> = {
  endpoint_not_configured: "Enter the gateway address.",
  endpoint_host_allowlist_not_configured: "List at least one allowed host.",
  endpoint_host_allowlist_invalid: "Allowed hosts are bare host names, without scheme, port, path or wildcard.",
  probe_contract_path_not_pinned: "Choose a supported models path.",
  probe_contract_response_shape_not_pinned: "Choose a supported response format.",
  probe_contract_model_group_field_not_pinned: "Choose a supported model name field.",
  form_request_timeout_seconds_out_of_range: "The timeout is outside the allowed range.",
  alias_catalog_has_no_admitted_alias: "Add at least one model.",
  form_alias_declared_twice: "Each model name may appear only once.",
  alias_not_requested: "Enter the model name.",
  alias_model_group_missing: "Enter the gateway model.",
  alias_context_limit_invalid: "Enter the context limit as a whole number.",
  alias_data_policy_class_invalid: "Choose up to which data class it is cleared.",
  alias_cost_source_unknown: "Choose how it is priced.",
  alias_cost_pricing_invalid: "Enter the input and output prices as numbers.",
  alias_cost_pricing_not_billable: "A model priced here needs a price above zero.",
  alias_cost_contract_reference_missing: "Enter the governance record.",
  alias_approved_data_categories_invalid: "The approved data categories are not valid.",
};

const words = (value: string) => {
  const text = value.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : value;
};

export const probePathLabel = (value: string) => PROBE_PATH_LABELS[value] ?? value;
export const responseShapeLabel = (value: string) => RESPONSE_SHAPE_LABELS[value] ?? words(value);
export const modelGroupFieldLabel = (value: string) => MODEL_GROUP_FIELD_LABELS[value] ?? words(value);
export const policyClassLabel = (value: string) => POLICY_CLASS_LABELS[value] ?? words(value);
export const costSourceLabel = (value: string) => COST_SOURCE_LABELS[value] ?? words(value);

/** A validation code of the gateway form as one sentence; an unknown code reads as its words, never as the code. */
export function gatewayCodeText(code: string): string {
  return CODE_TEXTS[code] ?? `${words(code)}.`;
}
