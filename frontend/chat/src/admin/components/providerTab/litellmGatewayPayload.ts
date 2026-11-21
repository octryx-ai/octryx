// LiteLLM gateway payload building: config section, config_json merge and create/update payloads.
import { approvedCategoriesEntry } from "./litellmGatewayApprovedCategories";
import {
  LITELLM_GATEWAY_CONFIG_KEY,
  LITELLM_GATEWAY_DRIVER,
  type GatewayAliasCost,
  type GatewayAliasCostDraft,
  type GatewayAliasDraft,
  type GatewayAliasEntry,
  type GatewayConfigSection,
  type GatewayCreatePayload,
  type GatewayDraft,
  type GatewayUpdatePayload,
} from "./litellmGatewayTypes";
import { parseHostAllowlist } from "./litellmGatewayValidation";

function buildAliasCost(cost: GatewayAliasCostDraft): GatewayAliasCost {
  if (cost.source === "catalog_pricing") {
    return {
      source: "catalog_pricing",
      input_per_million_usd: Number(cost.inputPerMillionUsd.trim()),
      output_per_million_usd: Number(cost.outputPerMillionUsd.trim()),
    };
  }
  return {
    source: cost.source,
    contract_reference: cost.contractReference.trim(),
  };
}

// The alias and cost keys this form renders; every other stored key is preserved.
export const GATEWAY_FORM_OWNED_ALIAS_KEYS = [
  "model_group",
  "context_limit",
  "data_policy_class",
  "capabilities",
  "cost",
  "approved_data_categories",
] as const;
export const GATEWAY_FORM_OWNED_COST_KEYS = [
  "source",
  "input_per_million_usd",
  "output_per_million_usd",
  "contract_reference",
] as const;

export function unownedKeys(
  raw: Record<string, unknown>,
  owned: readonly string[],
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(raw).filter(([key]) => !owned.includes(key)),
  );
}

function buildAliasEntry(alias: GatewayAliasDraft): GatewayAliasEntry {
  const preserved = alias.preserved;
  const cost = buildAliasCost(alias.cost);
  // Cache prices belong to the pricing contract they were declared with: a changed
  // cost source drops them instead of carrying them into a contract they do not fit.
  const preservedCost =
    preserved && preserved.costSource === alias.cost.source ? preserved.cost : {};
  return {
    ...(preserved?.entry ?? {}),
    model_group: alias.modelGroup.trim(),
    context_limit: Number(alias.contextLimit.trim()),
    data_policy_class: alias.dataPolicyClass,
    capabilities: { ...alias.capabilities },
    cost: { ...preservedCost, ...cost },
    ...approvedCategoriesEntry(alias.approvedDataCategories),
  };
}

export function buildGatewayConfigSection(
  draft: GatewayDraft,
): GatewayConfigSection {
  const aliases: Record<string, GatewayAliasEntry> = {};
  for (const alias of draft.aliases) {
    const name = alias.alias.trim();
    if (!name) {
      continue;
    }
    aliases[name] = buildAliasEntry(alias);
  }
  const section: GatewayConfigSection = {
    host_allowlist: parseHostAllowlist(draft.hostAllowlist),
    probe_contract: {
      models_path: draft.probeModelsPath,
      response_shape: draft.probeResponseShape,
      model_group_field: draft.probeModelGroupField,
    },
    aliases,
  };
  const timeout = draft.requestTimeoutSeconds.trim();
  if (timeout) {
    section.request_timeout_seconds = Number(timeout);
  }
  return section;
}

// The keys of the gateway section this form owns. Anything else inside the
// section is backend-governed configuration the form does not render — the
// transport trust store (`tls`), the optional governed proxy (`proxy`) and the
// content-logging posture (`content_logging`) — and it must
// survive an edit. See backend services/model_gateway/litellm/{transport_policy,
// content_logging}.py.
export const GATEWAY_FORM_OWNED_SECTION_KEYS = [
  "host_allowlist",
  "probe_contract",
  "aliases",
  "request_timeout_seconds",
] as const;

/**
 * Merge the governed section into the provider's existing config_json.
 * `PUT /providers/{id}` replaces config_json wholesale, so unrelated top-level
 * keys — and the governed section keys this form does not render — have to be
 * carried over instead of dropped. Dropping `tls` or `content_logging` would make
 * the provider unready, so an edit here must never silently do it.
 */
export function mergeGatewayConfigJson(
  existingConfigJson: unknown,
  section: GatewayConfigSection,
): Record<string, unknown> {
  const existing =
    existingConfigJson &&
    typeof existingConfigJson === "object" &&
    !Array.isArray(existingConfigJson)
      ? (existingConfigJson as Record<string, unknown>)
      : {};
  const existingSection = existing[LITELLM_GATEWAY_CONFIG_KEY];
  const carriedOver: Record<string, unknown> = {};
  if (
    existingSection &&
    typeof existingSection === "object" &&
    !Array.isArray(existingSection)
  ) {
    for (const [key, value] of Object.entries(
      existingSection as Record<string, unknown>,
    )) {
      if (
        !(GATEWAY_FORM_OWNED_SECTION_KEYS as readonly string[]).includes(key)
      ) {
        carriedOver[key] = value;
      }
    }
  }
  return {
    ...existing,
    [LITELLM_GATEWAY_CONFIG_KEY]: { ...carriedOver, ...section },
  };
}

export function buildGatewayCreatePayload(
  draft: GatewayDraft,
): GatewayCreatePayload {
  return {
    driver: LITELLM_GATEWAY_DRIVER,
    display_name: draft.displayName.trim() || LITELLM_GATEWAY_DRIVER,
    endpoint_url: draft.endpointUrl.trim(),
    config_json: mergeGatewayConfigJson({}, buildGatewayConfigSection(draft)),
    is_global: true,
  };
}

export function buildGatewayUpdatePayload(
  draft: GatewayDraft,
  existingConfigJson: unknown,
): GatewayUpdatePayload {
  return {
    display_name: draft.displayName.trim() || LITELLM_GATEWAY_DRIVER,
    endpoint_url: draft.endpointUrl.trim(),
    config_json: mergeGatewayConfigJson(
      existingConfigJson,
      buildGatewayConfigSection(draft),
    ),
  };
}
