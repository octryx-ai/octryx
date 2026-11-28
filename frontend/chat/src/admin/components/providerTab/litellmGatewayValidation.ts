import { approvedCategoriesCodes } from "./litellmGatewayApprovedCategories";
import {
  GATEWAY_COST_SOURCES,
  GATEWAY_DATA_POLICY_CLASSES,
  GATEWAY_FORM_CODE_ALIAS_DECLARED_TWICE,
  GATEWAY_FORM_CODE_TIMEOUT_OUT_OF_RANGE,
  GATEWAY_MAX_REQUEST_TIMEOUT_SECONDS,
  GATEWAY_MIN_REQUEST_TIMEOUT_SECONDS,
  GATEWAY_PROBE_MODEL_GROUP_FIELDS,
  GATEWAY_PROBE_PATHS,
  GATEWAY_PROBE_RESPONSE_SHAPES,
  type GatewayAliasDraft,
  type GatewayDraft,
} from "./litellmGatewayTypes";

export function parseHostAllowlist(raw: string): string[] {
  const seen = new Set<string>();
  for (const token of String(raw ?? "").split(/[\s,;]+/)) {
    const host = token.trim().toLowerCase();
    if (host) {
      seen.add(host);
    }
  }
  return Array.from(seen).sort();
}

// A scheme, port, path or wildcard would turn the allowlist into a matcher.
export function isBareAllowlistHost(host: string): boolean {
  const normalized = String(host ?? "")
    .trim()
    .toLowerCase();
  if (!normalized) {
    return false;
  }
  return !["/", ":", "@", "?", "#", "*", " "].some((token) =>
    normalized.includes(token),
  );
}

function positiveInteger(raw: string): number | null {
  const normalized = String(raw ?? "").trim();
  if (!/^\d+$/.test(normalized)) {
    return null;
  }
  const value = Number(normalized);
  return value > 0 ? value : null;
}

function nonNegativeNumber(raw: string): number | null {
  const normalized = String(raw ?? "").trim();
  if (!/^\d+(\.\d+)?$/.test(normalized)) {
    return null;
  }
  return Number(normalized);
}

export function aliasValidationCodes(alias: GatewayAliasDraft): string[] {
  const codes: string[] = [];
  if (!alias.alias.trim()) {
    codes.push("alias_not_requested");
  }
  if (!alias.modelGroup.trim()) {
    codes.push("alias_model_group_missing");
  }
  if (positiveInteger(alias.contextLimit) === null) {
    codes.push("alias_context_limit_invalid");
  }
  if (!GATEWAY_DATA_POLICY_CLASSES.includes(alias.dataPolicyClass)) {
    codes.push("alias_data_policy_class_invalid");
  }
  if (!GATEWAY_COST_SOURCES.includes(alias.cost.source)) {
    codes.push("alias_cost_source_unknown");
  } else if (alias.cost.source === "catalog_pricing") {
    const input = nonNegativeNumber(alias.cost.inputPerMillionUsd);
    const output = nonNegativeNumber(alias.cost.outputPerMillionUsd);
    if (input === null || output === null) {
      codes.push("alias_cost_pricing_invalid");
    } else if (input <= 0 || output <= 0) {
      // The backend refuses a zero rate at alias admission, so each rate must be billable on its own.
      codes.push("alias_cost_pricing_not_billable");
    }
  } else if (!alias.cost.contractReference.trim()) {
    codes.push("alias_cost_contract_reference_missing");
  }
  codes.push(...approvedCategoriesCodes(alias.approvedDataCategories));
  return codes;
}

export function gatewayValidationCodes(draft: GatewayDraft): {
  form: string[];
  aliases: Array<{ index: number; codes: string[] }>;
} {
  const form: string[] = [];
  if (!draft.endpointUrl.trim()) {
    form.push("endpoint_not_configured");
  }
  const hosts = parseHostAllowlist(draft.hostAllowlist);
  if (hosts.length === 0) {
    form.push("endpoint_host_allowlist_not_configured");
  } else if (!hosts.every(isBareAllowlistHost)) {
    form.push("endpoint_host_allowlist_invalid");
  }
  if (!GATEWAY_PROBE_PATHS.includes(draft.probeModelsPath)) {
    form.push("probe_contract_path_not_pinned");
  }
  if (!GATEWAY_PROBE_RESPONSE_SHAPES.includes(draft.probeResponseShape)) {
    form.push("probe_contract_response_shape_not_pinned");
  }
  if (!GATEWAY_PROBE_MODEL_GROUP_FIELDS.includes(draft.probeModelGroupField)) {
    form.push("probe_contract_model_group_field_not_pinned");
  }
  const timeout = draft.requestTimeoutSeconds.trim();
  if (timeout) {
    const seconds = nonNegativeNumber(timeout);
    if (
      seconds === null ||
      seconds < GATEWAY_MIN_REQUEST_TIMEOUT_SECONDS ||
      seconds > GATEWAY_MAX_REQUEST_TIMEOUT_SECONDS
    ) {
      form.push(GATEWAY_FORM_CODE_TIMEOUT_OUT_OF_RANGE);
    }
  }
  if (draft.aliases.length === 0) {
    form.push("alias_catalog_has_no_admitted_alias");
  }
  const names = draft.aliases.map((alias) => alias.alias.trim());
  if (new Set(names.filter(Boolean)).size !== names.filter(Boolean).length) {
    form.push(GATEWAY_FORM_CODE_ALIAS_DECLARED_TWICE);
  }
  const aliases = draft.aliases
    .map((alias, index) => ({ index, codes: aliasValidationCodes(alias) }))
    .filter((entry) => entry.codes.length > 0);
  return { form, aliases };
}

export function isGatewayDraftSubmittable(draft: GatewayDraft): boolean {
  const { form, aliases } = gatewayValidationCodes(draft);
  return form.length === 0 && aliases.length === 0;
}
