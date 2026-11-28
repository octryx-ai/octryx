import { isRecord, num, str, strings } from "./modelCatalogReaders";

export const CAPABILITY_KEYS = ["tools", "vision", "coding", "long_context"] as const;
export type CapabilityKey = (typeof CAPABILITY_KEYS)[number];
export const CAPABILITY_LABELS: Record<CapabilityKey, string> = {
  tools: "Tools", vision: "Vision", coding: "Coding", long_context: "Long context",
};
export const COST_SOURCES = ["catalog_pricing", "gateway_reported", "governed_free"] as const;
export type CostSource = (typeof COST_SOURCES)[number];
export const COST_SOURCE_LABELS: Record<CostSource, string> = {
  catalog_pricing: "Price list", gateway_reported: "Reported by the gateway", governed_free: "Free (governed)",
};
export const TEMPERATURE_CHOICES: readonly { value: number | null; label: string }[] = [
  { value: null, label: "Provider default" },
  { value: 0, label: "0 (most consistent)" },
  { value: 0.2, label: "0.2" },
  { value: 0.7, label: "0.7" },
];

export type CatalogIssue = { code: string; detail: string };
export type CatalogCost = {
  pricingInput: number | null; pricingOutput: number | null; pricingCacheRead: number | null;
  pricingCacheWrite: number | null; costSource: string | null; contractReference: string; editable: boolean;
};
export type CatalogRow = {
  id: string; catalogKey: string; modelId: string; displayName: string;
  provider: { id: string; displayName: string; isGateway: boolean; isActive: boolean };
  enabled: boolean; capabilities: Record<CapabilityKey, boolean>; clearedUpTo: string | null;
  approvedFor: string[]; temperature: number | null; maxOutputTokens: number | null; contextLength: number | null;
  cost: CatalogCost; usedBy: number; orderPosition: number | null;
  status: "enabled" | "off" | "needs_attention"; issues: CatalogIssue[];
};
export type CatalogProvider = { id: string; displayName: string };
export type Catalog = { models: CatalogRow[]; providers: CatalogProvider[]; levels: string[] };

function readRow(raw: Record<string, unknown>): CatalogRow | null {
  const id = str(raw.id);
  if (!id) return null;
  const provider = isRecord(raw.provider) ? raw.provider : {};
  const caps = isRecord(raw.capabilities) ? raw.capabilities : {};
  const cost = isRecord(raw.cost) ? raw.cost : {};
  const status = raw.status === "enabled" || raw.status === "off" || raw.status === "needs_attention" ? raw.status : "off";
  return {
    id, catalogKey: str(raw.catalog_key), modelId: str(raw.model_id),
    displayName: str(raw.display_name) || str(raw.model_id),
    provider: { id: str(provider.id), displayName: str(provider.display_name), isGateway: provider.is_gateway === true,
      isActive: provider.is_active !== false },
    enabled: raw.enabled === true,
    capabilities: Object.fromEntries(CAPABILITY_KEYS.map((key) => [key, caps[key] === true])) as Record<CapabilityKey, boolean>,
    clearedUpTo: str(raw.cleared_up_to) || null,
    approvedFor: strings(raw.approved_data_categories),
    temperature: num(raw.temperature), maxOutputTokens: num(raw.max_output_tokens), contextLength: num(raw.context_length),
    cost: {
      pricingInput: num(cost.pricing_input), pricingOutput: num(cost.pricing_output),
      pricingCacheRead: num(cost.pricing_cache_read), pricingCacheWrite: num(cost.pricing_cache_write),
      costSource: str(cost.cost_source) || null, contractReference: str(cost.contract_reference),
      editable: cost.editable === true,
    },
    usedBy: num(raw.used_by_workspaces) ?? 0, orderPosition: num(raw.order_position), status,
    issues: Array.isArray(raw.issues)
      ? raw.issues.filter(isRecord).map((issue) => ({ code: str(issue.code), detail: str(issue.detail) }))
      : [],
  };
}

export function readCatalogRow(payload: unknown): CatalogRow | null {
  return isRecord(payload) ? readRow(payload) : null;
}

export function readCatalog(payload: unknown): Catalog {
  const body = isRecord(payload) ? payload : {};
  const models = Array.isArray(body.models) ? body.models.filter(isRecord).map(readRow).filter((row): row is CatalogRow => row !== null) : [];
  const providers = Array.isArray(body.providers)
    ? body.providers.filter(isRecord).map((item) => ({ id: str(item.id), displayName: str(item.display_name) })).filter((item) => item.id)
    : [];
  return { models, providers, levels: strings(body.clearance_levels) };
}

export const levelLabel = (level: string | null): string => (level ? level.charAt(0).toUpperCase() + level.slice(1) : "—");

export function levelTone(level: string | null, levels: string[]): "attention" | "neutral" {
  const index = level ? levels.indexOf(level) : -1;
  return index >= 2 ? "attention" : "neutral";
}

const usd = (value: number) => `$${value.toFixed(2)}`;

export function priceText(row: CatalogRow): string {
  if (row.cost.costSource === "gateway_reported") return "Reported by the gateway";
  if (row.cost.costSource === "governed_free") return "Free (governed)";
  const { pricingInput: input, pricingOutput: output } = row.cost;
  if (input === null && output === null) return "—";
  return `${input === null ? "—" : usd(input)} · ${output === null ? "—" : usd(output)}`;
}

export function usedByText(row: CatalogRow): string {
  if (!row.usedBy) return "None";
  return `${row.usedBy} ${row.usedBy === 1 ? "Workspace" : "Workspaces"}`;
}

export const orderTag = (row: CatalogRow): string => (row.orderPosition ? `· order #${row.orderPosition}` : "");

const ISSUE_TEXT: Record<string, string> = {
  no_alias: "Not callable: no gateway alias",
  alias_incomplete: "Not callable: the gateway alias is incomplete",
  gone_upstream: "Gone upstream: the provider no longer lists it",
  provider_off: "The provider connection is disabled",
  not_cleared: "Enabled, but not cleared for any data class",
  cost_drift: "Shown prices differ from what the gateway charges: save the cost again",
};
export const issueText = (issue: CatalogIssue): string => ISSUE_TEXT[issue.code] ?? "Needs attention";

export const providerOff = (row: CatalogRow): boolean => !row.provider.isActive;
export const isOn = (row: CatalogRow): boolean => row.enabled && !providerOff(row);
export const needsAttention = (row: CatalogRow): boolean => isOn(row) && row.status === "needs_attention";

export function statusView(row: CatalogRow): { label: string; tone: "active" | "neutral" | "attention"; title: string } {
  const issues = row.issues.map(issueText).join(". ");
  if (needsAttention(row)) return { label: "Needs attention", tone: "attention", title: issues };
  if (row.enabled && providerOff(row)) {
    const title = row.issues.some((issue) => issue.code === "provider_off") ? issues : [ISSUE_TEXT.provider_off, issues].filter(Boolean).join(". ");
    return { label: "Provider off", tone: "neutral", title };
  }
  return row.enabled ? { label: "Enabled", tone: "active", title: "" } : { label: "Off", tone: "neutral", title: issues };
}

export type StatusFilter = "" | "on" | "off" | "issue";
export type CatalogScope = "inUse" | "all";

export const inUse = (row: CatalogRow): boolean => row.usedBy > 0 || isOn(row);

export function filterRows(rows: CatalogRow[], providerId: string, status: StatusFilter, scope: CatalogScope = "all"): CatalogRow[] {
  return rows.filter((row) => (!providerId || row.provider.id === providerId) && (scope === "all" || inUse(row)) && (
    !status || (status === "on" ? isOn(row) : status === "off" ? !isOn(row) : needsAttention(row))));
}

export function sortRows(rows: CatalogRow[]): CatalogRow[] {
  const group = (row: CatalogRow) => (row.usedBy > 0 ? 0 : isOn(row) ? 1 : 2);
  const order = (row: CatalogRow) => row.orderPosition ?? Number.MAX_SAFE_INTEGER;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => group(a.row) - group(b.row) || order(a.row) - order(b.row) || a.index - b.index)
    .map(({ row }) => row);
}

export type ModelDraft = {
  enabled: boolean; displayName: string; capabilities: Record<CapabilityKey, boolean>; clearedUpTo: string | null;
  approvedFor: string[]; temperature: number | null; maxOutputTokens: string; contextLength: string;
  costSource: CostSource; pricingInput: string; pricingOutput: string; pricingCacheRead: string;
  pricingCacheWrite: string; contractReference: string;
};

const numberText = (value: number | null) => (value === null ? "" : String(value));

export function draftFromRow(row: CatalogRow): ModelDraft {
  const source = COST_SOURCES.includes(row.cost.costSource as CostSource) ? (row.cost.costSource as CostSource) : "catalog_pricing";
  return {
    enabled: row.enabled, displayName: row.displayName, capabilities: { ...row.capabilities },
    clearedUpTo: row.clearedUpTo, approvedFor: [...row.approvedFor].sort(), temperature: row.temperature,
    maxOutputTokens: numberText(row.maxOutputTokens), contextLength: numberText(row.contextLength), costSource: source,
    pricingInput: numberText(row.cost.pricingInput), pricingOutput: numberText(row.cost.pricingOutput),
    pricingCacheRead: numberText(row.cost.pricingCacheRead), pricingCacheWrite: numberText(row.cost.pricingCacheWrite),
    contractReference: row.cost.contractReference,
  };
}

const priceValue = (text: string): number | null => (text.trim() === "" ? null : Number(text.trim()));
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function catalogPatch(row: CatalogRow, draft: ModelDraft): Record<string, unknown> {
  const base = draftFromRow(row);
  const patch: Record<string, unknown> = {};
  if (draft.enabled !== base.enabled) patch.enabled = draft.enabled;
  if (draft.displayName.trim() !== base.displayName) patch.display_name = draft.displayName.trim();
  if (!same(draft.capabilities, base.capabilities)) patch.capabilities = { ...draft.capabilities };
  if (draft.clearedUpTo !== base.clearedUpTo) patch.cleared_up_to = draft.clearedUpTo;
  if (!same([...draft.approvedFor].sort(), base.approvedFor)) patch.approved_data_categories = [...draft.approvedFor].sort();
  if (draft.temperature !== base.temperature) patch.temperature = draft.temperature;
  if (draft.maxOutputTokens.trim() !== base.maxOutputTokens) {
    patch.max_output_tokens = draft.maxOutputTokens.trim() === "" ? null : Number(draft.maxOutputTokens.trim());
  }
  // A gateway model's context window comes from its gateway contract.
  if (!row.provider.isGateway && draft.contextLength.trim() !== base.contextLength) {
    patch.context_length = draft.contextLength.trim() === "" ? null : Number(draft.contextLength.trim());
  }
  const costKeys = ["costSource", "pricingInput", "pricingOutput", "pricingCacheRead", "pricingCacheWrite", "contractReference"] as const;
  if (row.cost.editable && costKeys.some((key) => draft[key] !== base[key])) {
    const prices = {
      pricing_input: priceValue(draft.pricingInput), pricing_output: priceValue(draft.pricingOutput),
      pricing_cache_read: priceValue(draft.pricingCacheRead), pricing_cache_write: priceValue(draft.pricingCacheWrite),
    };
    if (!row.provider.isGateway) patch.cost = prices;
    else if (draft.costSource === "catalog_pricing") patch.cost = { cost_source: draft.costSource, ...prices };
    else patch.cost = { cost_source: draft.costSource, contract_reference: draft.contractReference.trim() };
  }
  return patch;
}

export function draftProblems(draft: ModelDraft, row: CatalogRow): string[] {
  const problems: string[] = [];
  const name = draft.displayName.trim();
  if (!name || name.length > 80) problems.push("The display name needs 1 to 80 characters.");
  const max = draft.maxOutputTokens.trim();
  if (max && !(Number.isInteger(Number(max)) && Number(max) >= 256)) problems.push("The longest answer is a whole number of at least 256 tokens, or empty.");
  const context = draft.contextLength.trim();
  if (!row.provider.isGateway && context && !(Number.isInteger(Number(context)) && Number(context) >= 1000 && Number(context) <= 10000000)) {
    problems.push("The context window is a whole number of 1,000 to 10,000,000 tokens, or empty.");
  }
  if (row.cost.editable && row.provider.isGateway) {
    if (draft.costSource === "catalog_pricing" && !(Number(draft.pricingInput) > 0 && Number(draft.pricingOutput) > 0)) {
      problems.push("A price list needs an input and an output price above zero.");
    }
    if (draft.costSource !== "catalog_pricing" && !draft.contractReference.trim()) {
      problems.push("Name the contract record this cost source is governed by.");
    }
  }
  return problems;
}

export function isClearanceRaise(row: CatalogRow, draft: ModelDraft, levels: string[]): boolean {
  const before = row.clearedUpTo ? levels.indexOf(row.clearedUpTo) : -1;
  const after = draft.clearedUpTo ? levels.indexOf(draft.clearedUpTo) : -1;
  return after > before;
}

const SAVE_CODES: Record<string, string> = {
  model_catalog_display_name_invalid: "the display name is empty or too long",
  model_catalog_capabilities_invalid: "the capabilities are not valid",
  model_catalog_approved_categories_invalid: "a data category is not valid",
  model_catalog_temperature_invalid: "the temperature must be between 0 and 2",
  model_catalog_max_output_invalid: "the longest answer must be at least 256 tokens",
  model_catalog_context_length_invalid: "the context window must be 1,000 to 10,000,000 tokens",
  model_catalog_context_length_governed: "a gateway model's context window comes from its gateway contract",
  model_catalog_cost_invalid: "the prices are not valid for this cost source",
  model_catalog_cost_governed: "the price is owned by the provider's price list",
  model_catalog_clearance_invalid: "the clearance level is not valid",
  model_catalog_model_not_found: "the model no longer exists",
  model_catalog_alias_exists: "the gateway already has an alias for this model",
};

export function saveErrorText(error: unknown): string {
  const record = isRecord(error) ? error : {};
  const code = str(record.code) || (isRecord(record.detail) ? str(record.detail.code) : "");
  if (record.status === 403) return "Not saved: only platform admins can change the Model catalog.";
  return `Not saved: ${SAVE_CODES[code] ?? (str(record.message) || "the change was refused")}.`;
}
