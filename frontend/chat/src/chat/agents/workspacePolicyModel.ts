import { readSegments } from "../../admin/components/policyEngine/policyCatalogModel";
import type { Segment } from "../../admin/components/policyEngine/policyCatalogModel";
import { RULE_COLUMNS, connectorModeText, familyLabel } from "../../admin/components/dataClassification/classificationPolicyModel";
import { seatReasonText } from "../../admin/components/dataClassification/dataClassificationSeat";

// Agents → Governance → "Policy": the effective policy of one Workspace, read-only for every member. Pure: no
// requests, no React. Every line states what the server answered; nothing is guessed for a missing fact.
//
// Contract (backend services/data_classification/workspace_policy_summary.py):
//   GET /api/v1/workspaces/{id}/policy-summary (members; a non-member gets 404) ->
//   {classification: {effective, source: workspace|instance_default|unset}, matrix_state, rules: {<level rules>}|null,
//    seat: {seat_mode, seat_mode_set, in_effect, reason}, agent_gateway_policy: {state: ok|needs_configuration, reason, source,
//    tool_rules: [{id, kind, target: {command, argument?} | {tools, glob}}], client_permissions: {deny, ask}},
//    models: {allowed_aliases, denied: [{alias, reason}]}, budgets: {per_user_daily_usd | session_cost_limit_usd |
//    request_cost_limit_usd: {value_usd, source}}, connectors: {<family>: none|read|read_write}|null,
//    can_edit: platform admin (the matrix's rule; the view links only to platform-admin settings)}

export type RuleLine = { key: string; label: string; allowed: boolean | null; value: string };
export type ToolRuleLine = { id: string; subject: string; text: string };
export type BudgetLine = { key: string; label: string; value: string; source: string | null };

export type GatewayPolicyState = { ok: boolean; reason: string | null; source: string | null };

export type WorkspacePolicy = {
  classification: string | null;
  classificationSource: string | null;
  matrixInvalid: boolean;
  rules: RuleLine[];
  gateway: GatewayPolicyState | null;
  deniedModels: { alias: string; reason: string }[];
  // `set`: whether the Workspace stored its seat switch (`seat_mode_set`); null when the server did not say.
  seat: { mode: string | null; set: boolean | null; inEffect: boolean | null; reason: string | null } | null;
  toolRules: ToolRuleLine[] | null;
  clientPermissions: ToolRuleLine[];
  models: string[] | null;
  budgets: BudgetLine[] | null;
  connectors: { family: string; label: string; mode: string }[] | null;
  /** Policy UX: the published platform policies that apply here (`null`: the server did not state them). */
  platformPolicies: PlatformPolicyLine[] | null;
  canEdit: boolean;
};

export type PlatformPolicyLine = { id: string; name: string; source: string; sentence: Segment[]; conditional: boolean };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");
const flag = (value: unknown) => (typeof value === "boolean" ? value : null);
const texts = (value: unknown) => (Array.isArray(value) ? value.map((item) => text(isRecord(item) ? item.alias : item)).filter(Boolean) : null);
const first = (record: Record<string, unknown>, ...keys: string[]) => keys.map((key) => record[key]).find((value) => value !== undefined);

const SOURCE_TEXT: Record<string, string> = {
  workspace: "set for this Workspace",
  instance_default: "Instance default",
  unset: "not set",
  configured: "set by a platform admin",
  global: "instance-wide setting",
  default: "built-in default",
  baseline: "built-in baseline",
};
export const sourceWords = (source: string | null) => (source ? SOURCE_TEXT[source] || source : null);

/** The level's rules as ✓/✗ lines, in the matrix's column order; connectors are listed on their own. */
export function ruleLines(rules: unknown): RuleLine[] {
  if (!isRecord(rules)) return [];
  const lines: RuleLine[] = [];
  for (const column of RULE_COLUMNS) {
    const value = rules[column.key];
    if (value === undefined || column.kind === "connectors") continue;
    if (column.kind === "bool") {
      if (typeof value !== "boolean") continue;
      // "Required" rules restrict: on is the stricter state, so they read as a requirement, not a permission.
      lines.push({ key: column.key, label: column.label, allowed: column.yes === "required" ? null : value, value: value ? column.yes ?? "on" : column.no ?? "off" });
    } else if (column.kind === "aliases") {
      lines.push({ key: column.key, label: column.label, allowed: null, value: Array.isArray(value) ? texts(value)!.join(", ") || "no company model" : "All admitted" });
    } else {
      lines.push({ key: column.key, label: column.label, allowed: null, value: typeof value === "number" ? `${value} ${value === 1 ? "day" : "days"}` : "kept" });
    }
  }
  return lines;
}

const tokens = (value: unknown) => (Array.isArray(value) ? value.map(text).filter(Boolean).join(" ") : text(value));

/** One tool rule in words ("`kubectl delete` blocked"); an unknown kind is named, never dropped. */
export function toolRuleLine(value: unknown, index: number): ToolRuleLine | null {
  if (!isRecord(value)) return null;
  // The summary nests what a rule applies to in `target`; the stored policy keeps it on the rule itself.
  const rule = isRecord(value.target) ? { ...value, ...value.target } : value;
  const id = text(rule.id) || `rule-${index + 1}`;
  const kind = text(rule.kind);
  const command = tokens(rule.command);
  const argument = text(rule.argument);
  const tools = Array.isArray(rule.tools) ? rule.tools.map(text).filter(Boolean) : [];
  if (kind === "command_prefix_denied") return { id, subject: tokens(rule.prefix) || command, text: "blocked" };
  if (kind === "command_argument_denied") return { id, subject: `${command} ${argument}`.trim(), text: "blocked" };
  if (kind === "command_requires_argument") return { id, subject: command, text: `only with ${argument}` };
  if (kind === "path_denied") {
    const glob = text(rule.glob).replace(/^\*\*\//, "");
    return { id, subject: glob, text: `files blocked${tools.length ? ` for ${tools.join(", ")}` : ""}` };
  }
  const target = tokens(first(rule, "prefix", "glob", "command"));
  return { id, subject: target || id, text: kind ? `rule (${kind})` : "rule" };
}

function permissionLines(value: unknown): ToolRuleLine[] {
  if (!isRecord(value)) return [];
  const lines: ToolRuleLine[] = [];
  for (const [kind, words] of [["deny", "denied in the agent client"], ["ask", "asks first in the agent client"]] as const) {
    (texts(value[kind]) ?? []).forEach((entry, index) => lines.push({ id: `${kind}-${index}`, subject: entry, text: words }));
  }
  return lines;
}

const BUDGET_LABELS: Record<string, string> = {
  per_user_daily_usd: "Per user and day", session_cost_limit_usd: "Per session", request_cost_limit_usd: "Per request",
};
// A cost limit of 0 is off (backend budget/agent_cost_limits); an unset daily budget is no limit.
const usd = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? (value === 0 ? "off" : `$${value}`) : value === null ? "no limit" : null;

/** Budgets from `{key: {value_usd, source}}`, `{key: number}` or `[{key, value_usd, source}]`; null when not stated. */
export function budgetLines(value: unknown): BudgetLine[] | null {
  if (!Array.isArray(value) && !isRecord(value)) return null;
  const entries: [string, unknown][] = Array.isArray(value)
    ? value.filter(isRecord).map((entry) => [text(first(entry, "key", "kind", "name")), entry])
    : Object.entries(value);
  const lines: BudgetLine[] = [];
  for (const [key, entry] of entries) {
    if (!key) continue;
    const record = isRecord(entry) ? entry : { value_usd: entry };
    const amount = usd(first(record, "value_usd", "limit_usd", "value", "usd"));
    if (amount === null) continue;
    lines.push({ key, label: text(record.label) || BUDGET_LABELS[key] || key, value: amount, source: sourceWords(text(record.source) || null) });
  }
  return lines;
}

const DENIED_MODEL_TEXT: Record<string, string> = {
  model_alias_not_granted_for_project: "not granted to this Workspace",
  model_alias_not_allowed_for_classification: "not in the classification policy's list for this level",
  data_policy_class_insufficient: "its data policy does not admit this level",
  explicit_alias_denial: "denied for this Workspace by its model policy",
  alias_data_policy_class_unknown: "the gateway states no data policy for it",
  data_policy_context_unverifiable: "the Workspace's data classification could not be verified",
  project_policy_context_unverifiable: "the Workspace's model policy could not be verified",
};
const deniedModelText = (reason: string) => DENIED_MODEL_TEXT[reason] || reason;

/** The Workspace policy read model; null when the answer is not an object. */
export function readWorkspacePolicy(payload: unknown): WorkspacePolicy | null {
  if (!isRecord(payload)) return null;
  const classification = isRecord(payload.classification) ? payload.classification : {};
  const seat = isRecord(payload.seat) ? payload.seat : null;
  const gateway = isRecord(payload.agent_gateway_policy) ? payload.agent_gateway_policy : null;
  const models = isRecord(payload.models) ? first(payload.models, "allowed_aliases", "aliases") : first(payload, "allowed_models", "models");
  const connectors = isRecord(payload.connectors) ? payload.connectors : null;
  const denied = isRecord(payload.models) && Array.isArray(payload.models.denied) ? payload.models.denied : [];
  return {
    classification: text(first(classification, "label", "effective", "level")) || null,
    classificationSource: text(classification.source) || null,
    matrixInvalid: payload.matrix_state === "invalid",
    rules: ruleLines(first(payload, "rules", "level_rules")),
    gateway: gateway ? { ok: text(gateway.state) !== "needs_configuration", reason: text(gateway.reason) || null, source: text(gateway.source) || null } : null,
    deniedModels: denied.filter(isRecord).map((entry) => ({ alias: text(entry.alias), reason: deniedModelText(text(entry.reason)) }))
      .filter((entry) => entry.alias),
    seat: seat ? { mode: text(seat.seat_mode) || null, set: typeof seat.seat_mode_set === "boolean" ? seat.seat_mode_set : null,
      inEffect: flag(seat.in_effect), reason: text(seat.reason) || null } : null,
    toolRules: gateway && Array.isArray(gateway.tool_rules)
      ? gateway.tool_rules.map(toolRuleLine).filter((line): line is ToolRuleLine => line !== null) : null,
    clientPermissions: gateway ? permissionLines(gateway.client_permissions) : [],
    models: texts(models),
    budgets: budgetLines(payload.budgets),
    connectors: connectors ? Object.entries(connectors).map(([family, mode]) => ({ family, label: familyLabel(family), mode: connectorModeText(mode) })) : null,
    platformPolicies: platformPolicyLines(payload.platform_policies),
    canEdit: payload.can_edit === true,
  };
}

function platformPolicyLines(raw: unknown): PlatformPolicyLine[] | null {
  if (!isRecord(raw) || !Array.isArray(raw.items)) return null;
  return raw.items.filter(isRecord).map((item) => ({
    id: text(item.id), name: text(item.name) || text(item.id), source: text(item.source), sentence: readSegments(item.sentence),
    conditional: item.conditional === true,
  })).filter((item) => item.id);
}

/** The seat state in one sentence. */
export function seatText(seat: WorkspacePolicy["seat"]): string {
  if (!seat) return "The server did not state the seat state.";
  // An unset switch is open at public/internal data (seat_mode_set); servers without the flag: inferred.
  const unset = seat.set === false || (seat.set === null && seat.mode === "forbidden" && seat.inEffect === true);
  const stored = unset ? (seat.inEffect === true ? "The Workspace allows seat sessions by default (public/internal data)"
      : "The Workspace does not allow seat sessions by default (confidential data or above)")
    : seat.mode === "allowed" ? "The Workspace allows seat sessions"
      : seat.mode === "forbidden" ? "The Workspace does not allow seat sessions" : "The seat switch is unknown";
  if (seat.inEffect === true) return `${stored}; seat sessions can run here.`;
  if (seat.inEffect === false) return `${stored}; seat sessions are refused here: ${seatReasonText(seat.reason)}.`;
  return `${stored}.`;
}

export function policyLoadErrorText(error: unknown): string {
  const record = isRecord(error) ? error : null;
  if (record?.status === 404) return "No policy is shown: this server does not offer it yet, or you are not a member of this Workspace.";
  if (record?.status === 401 || record?.status === 403) return "Only members of this Workspace can see its policy.";
  const message = typeof record?.message === "string" && record.message ? record.message : "the request failed";
  return `The Workspace policy could not be loaded: ${message}.`;
}
