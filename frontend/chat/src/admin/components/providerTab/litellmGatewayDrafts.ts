// Empty LiteLLM gateway drafts and drafts seeded from a stored provider row.
import { readApprovedCategories } from "./litellmGatewayApprovedCategories";
import {
  GATEWAY_FORM_OWNED_ALIAS_KEYS,
  GATEWAY_FORM_OWNED_COST_KEYS,
  unownedKeys,
} from "./litellmGatewayPayload";
import {
  GATEWAY_CAPABILITIES,
  GATEWAY_COST_SOURCES,
  GATEWAY_DATA_POLICY_CLASSES,
  GATEWAY_PROBE_MODEL_GROUP_FIELDS,
  GATEWAY_PROBE_PATHS,
  GATEWAY_PROBE_RESPONSE_SHAPES,
  LITELLM_GATEWAY_CONFIG_KEY,
  type GatewayAliasDraft,
  type GatewayAliasPreserved,
  type GatewayCapability,
  type GatewayCostSource,
  type GatewayDraft,
} from "./litellmGatewayTypes";

export function emptyGatewayCapabilities(): Record<GatewayCapability, boolean> {
  return {
    tools: false,
    structured_output: false,
    reasoning: false,
    vision: false,
  };
}

export function emptyGatewayAliasDraft(): GatewayAliasDraft {
  return {
    alias: "",
    modelGroup: "",
    contextLimit: "",
    dataPolicyClass: "internal",
    capabilities: emptyGatewayCapabilities(),
    cost: {
      source: "catalog_pricing",
      inputPerMillionUsd: "",
      outputPerMillionUsd: "",
      contractReference: "",
    },
    approvedDataCategories: [],
  };
}

export function emptyGatewayDraft(): GatewayDraft {
  return {
    displayName: "",
    endpointUrl: "",
    hostAllowlist: "",
    probeModelsPath: "/models",
    probeResponseShape: "openai_model_list",
    probeModelGroupField: "id",
    requestTimeoutSeconds: "",
    aliases: [emptyGatewayAliasDraft()],
  };
}

function closedValue<T extends string>(
  raw: unknown,
  allowed: readonly T[],
  fallback: T,
): T {
  const normalized = String(raw ?? "")
    .trim()
    .toLowerCase();
  return (allowed as readonly string[]).includes(normalized)
    ? (normalized as T)
    : fallback;
}

function aliasDraftFromEntry(alias: string, raw: unknown): GatewayAliasDraft {
  const entry =
    raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {};
  const rawCapabilities =
    entry.capabilities && typeof entry.capabilities === "object"
      ? (entry.capabilities as Record<string, unknown>)
      : {};
  const capabilities = emptyGatewayCapabilities();
  for (const capability of GATEWAY_CAPABILITIES) {
    capabilities[capability] = rawCapabilities[capability] === true;
  }
  const rawCost =
    entry.cost && typeof entry.cost === "object"
      ? (entry.cost as Record<string, unknown>)
      : {};
  const source = closedValue(
    rawCost.source,
    GATEWAY_COST_SOURCES,
    "catalog_pricing",
  );
  return {
    alias,
    modelGroup: typeof entry.model_group === "string" ? entry.model_group : "",
    contextLimit:
      typeof entry.context_limit === "number"
        ? String(entry.context_limit)
        : "",
    dataPolicyClass: closedValue(
      entry.data_policy_class,
      GATEWAY_DATA_POLICY_CLASSES,
      "internal",
    ),
    capabilities,
    cost: {
      source,
      inputPerMillionUsd:
        typeof rawCost.input_per_million_usd === "number"
          ? String(rawCost.input_per_million_usd)
          : "",
      outputPerMillionUsd:
        typeof rawCost.output_per_million_usd === "number"
          ? String(rawCost.output_per_million_usd)
          : "",
      contractReference:
        typeof rawCost.contract_reference === "string"
          ? rawCost.contract_reference
          : "",
    },
    approvedDataCategories: readApprovedCategories(
      entry.approved_data_categories,
    ),
    ...preservedAliasKeys(entry, rawCost, source),
    stored: true,
  };
}

function preservedAliasKeys(
  entry: Record<string, unknown>,
  rawCost: Record<string, unknown>,
  costSource: GatewayCostSource,
): { preserved?: GatewayAliasPreserved } {
  const preservedEntry = unownedKeys(entry, GATEWAY_FORM_OWNED_ALIAS_KEYS);
  const preservedCost = unownedKeys(rawCost, GATEWAY_FORM_OWNED_COST_KEYS);
  if (!Object.keys(preservedEntry).length && !Object.keys(preservedCost).length) {
    return {};
  }
  return { preserved: { entry: preservedEntry, cost: preservedCost, costSource } };
}

/** Seed the edit form from a serialized provider row. */
export function gatewayDraftFromProvider(provider: {
  display_name?: string;
  endpoint_url?: string;
  config_json?: unknown;
}): GatewayDraft {
  const configJson =
    provider.config_json && typeof provider.config_json === "object"
      ? (provider.config_json as Record<string, unknown>)
      : {};
  const rawSection = configJson[LITELLM_GATEWAY_CONFIG_KEY];
  const section =
    rawSection && typeof rawSection === "object" && !Array.isArray(rawSection)
      ? (rawSection as Record<string, unknown>)
      : {};
  const rawProbe =
    section.probe_contract && typeof section.probe_contract === "object"
      ? (section.probe_contract as Record<string, unknown>)
      : {};
  const rawAliases =
    section.aliases &&
    typeof section.aliases === "object" &&
    !Array.isArray(section.aliases)
      ? (section.aliases as Record<string, unknown>)
      : {};
  const aliases = Object.keys(rawAliases).map((alias) =>
    aliasDraftFromEntry(alias, rawAliases[alias]),
  );
  return {
    displayName: provider.display_name || "",
    endpointUrl: provider.endpoint_url || "",
    hostAllowlist: Array.isArray(section.host_allowlist)
      ? (section.host_allowlist as unknown[])
          .filter((host): host is string => typeof host === "string")
          .join(", ")
      : "",
    probeModelsPath: closedValue(
      rawProbe.models_path,
      GATEWAY_PROBE_PATHS,
      "/models",
    ),
    probeResponseShape: closedValue(
      rawProbe.response_shape,
      GATEWAY_PROBE_RESPONSE_SHAPES,
      "openai_model_list",
    ),
    probeModelGroupField: closedValue(
      rawProbe.model_group_field,
      GATEWAY_PROBE_MODEL_GROUP_FIELDS,
      "id",
    ),
    requestTimeoutSeconds:
      typeof section.request_timeout_seconds === "number"
        ? String(section.request_timeout_seconds)
        : "",
    aliases: aliases.length > 0 ? aliases : [emptyGatewayAliasDraft()],
  };
}
