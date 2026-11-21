// Added classification rules from the effect catalog: reading, sentences and generated policy text.
import type { CatalogLevel } from "./classificationLevelCatalog";
import { isRecord, list, text } from "./classificationValueReaders";

// ---- added rules from the effect catalog --------------------------------------------------------

export type EffectType = { key: string; label: string; description: string; param: "none" | "server"; enforced: boolean; enforcedAt: string };
export type EffectRule = { effect: string; param: string; from_level: string };

export function readEffects(payload: unknown): { catalog: EffectType[]; published: EffectRule[]; draft: EffectRule[] | null; servers: string[] } {
  const record = isRecord(payload) ? payload : {};
  const rules = (value: unknown) => list(value).filter(isRecord).map((item) => ({
    effect: text(item.effect), param: text(item.param) || "off", from_level: text(item.from_level),
  }));
  const draft = isRecord(record.draft) && Array.isArray(record.draft.effect_rules) ? rules(record.draft.effect_rules) : null;
  return {
    catalog: list(record.effect_catalog).filter(isRecord).map((item) => ({
      key: text(item.key), label: text(item.label), description: text(item.description),
      param: item.param === "server" ? "server" : "none", enforced: item.enforced === true, enforcedAt: text(item.enforced_at),
    })),
    published: rules(record.effect_rules),
    draft,
    servers: list(record.mcp_servers).map(text).filter(Boolean),
  };
}

export const effectRuleId = (rule: EffectRule) => (rule.effect === "mcp_server" ? `${rule.effect}:${rule.param}` : rule.effect);

export function effectTarget(rule: EffectRule): string {
  if (rule.effect !== "mcp_server") return "";
  return rule.param === "*" ? "every server" : rule.param;
}

export function effectRuleSentence(rule: EffectRule, catalog: EffectType[], levelLabel: (key: string) => string): string {
  const label = catalog.find((item) => item.key === rule.effect)?.label ?? rule.effect;
  const target = effectTarget(rule);
  return `In Workspaces at ${levelLabel(rule.from_level)} or above, ${label}${target ? ` (${target})` : ""} is off. Below ${levelLabel(rule.from_level)} nothing changes.`;
}

/** Whether a rule restricts a level: at and above its threshold, by rank. */
export function effectApplies(rule: EffectRule, level: CatalogLevel, catalog: CatalogLevel[]): boolean {
  const from = catalog.find((item) => item.key === rule.from_level);
  return Boolean(from) && level.rank >= (from as CatalogLevel).rank;
}

/** The generated policy text of an added rule (the backend's ``policy_preview.effect_policies``). */
export function effectPolicyText(rule: EffectRule, catalog: CatalogLevel[], sentence: string): string {
  const rank = catalog.find((item) => item.key === rule.from_level)?.rank ?? 0;
  const resource = rule.effect === "web_search" ? 'resource == Tool::"web_search"' : "resource";
  const action = rule.effect === "knowledge_sharing" ? "read_connector" : "call_tool";
  return [`// ${sentence}`, `@id("classification:${rule.from_level}+:${effectRuleId(rule).replace(":", "-")}")`,
    `forbid (principal, action == Action::"${action}", ${resource})`,
    `  when { context.workspace has classification_rank && context.workspace.classification_rank >= ${rank} };`].join("\n");
}
