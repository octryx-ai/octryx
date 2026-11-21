// Pure model of the If / else step (node type "router"). It presents the existing contract
// in plain words and never changes it on its own:
// - rules are checked top to bottom; the first match picks its branch, otherwise `default_route`
//   (dag_executor._execute_router_node);
// - a rule is `{route|target, when: {field, operator, value}}`;
// - a connection out of the step runs for a branch when its condition is the branch name,
//   `route:<name>` or `{route: <name>}`; a connection without a condition runs when no other
//   connection matches; with neither, the run fails at the step (`router_branch_unmatched`)
//   and nothing after it runs (flow_orchestration/router_branches.py). Custom predicate
//   conditions are decided only at run time, so this model never claims they do not match.
// Saved operator spellings, value types and custom conditions are kept as they are. Whether a
// condition can run is read with the graph labels' shared reading (flowConditionShape).
import { conditionShape, isRecord, normalizeOperator } from "./flowConditionShape";
import type { RouterRule } from "./flowRouterRule";

export type ValueType = "text" | "number" | "boolean" | "text_list" | "number_list" | "none";

type OperatorInfo = { label: string; types: ValueType[] };

// Operators the runtime evaluates (dag_executor._operator_condition_matches), with plain labels and
// the value types that make sense for them. Aliases keep their saved spelling.
const OPERATORS: Record<string, OperatorInfo> = {
  equals: { label: "is equal to", types: ["text", "number", "boolean"] },
  not_equals: { label: "is not equal to", types: ["text", "number", "boolean"] },
  contains: { label: "contains", types: ["text", "number"] },
  not_contains: { label: "does not contain", types: ["text", "number"] },
  in: { label: "is one of", types: ["text_list", "number_list"] },
  not_in: { label: "is not one of", types: ["text_list", "number_list"] },
  gt: { label: "is greater than", types: ["number"] },
  gte: { label: "is at least", types: ["number"] },
  lt: { label: "is less than", types: ["number"] },
  lte: { label: "is at most", types: ["number"] },
  exists: { label: "has a value (yes) / is missing (no)", types: ["boolean"] },
  truthy: { label: "is filled in and not false/0 (yes) / is empty (no)", types: ["boolean"] },
};

const ALIASES: Record<string, string> = { eq: "equals", "==": "equals", neq: "not_equals", "!=": "not_equals" };

export const OPERATOR_CHOICES = Object.keys(OPERATORS);

export const VALUE_TYPE_LABELS: Record<ValueType, string> = {
  text: "Text",
  number: "Number",
  boolean: "Yes / no",
  text_list: "List of texts",
  number_list: "List of numbers",
  none: "No value",
};

// The canonical operator for a saved spelling: case and spaces ignored, aliases resolved.
function canonicalOperator(operator: string): string {
  const normalized = normalizeOperator(operator);
  return ALIASES[normalized] ?? normalized;
}

export function operatorLabel(operator: string): string {
  const canonical = canonicalOperator(operator);
  const known = OPERATORS[canonical];
  if (!known) return `${operator} (not supported: the workflow stops at this step until you choose another comparison)`;
  return operator !== canonical ? `${known.label} (saved as ${operator})` : known.label;
}

export function operatorValueTypes(operator: string): ValueType[] {
  return OPERATORS[canonicalOperator(operator)]?.types ?? [];
}

// Whether the server can check a condition: "invalid" blocks the step, "uncertain" is left to it.
export type ConditionCheck = { state: "ok" } | { state: "invalid" | "uncertain"; reason: string };

// How a rule's condition is stored, so edits write back into the same shape. The saved operator
// spelling is kept as written ("GT", " eq "); only the check uses the normalised one.
export type RuleCondition =
  | { form: "operator"; field: string; operator: string; value: unknown; hasValue: boolean; check: ConditionCheck }
  | { form: "always" }
  | { form: "custom"; raw: unknown; check: ConditionCheck };

function checkOf(when: unknown): ConditionCheck {
  const shape = conditionShape(when);
  return shape.state === "invalid" || shape.state === "uncertain" ? { state: shape.state, reason: shape.reason } : { state: "ok" };
}

export function readRuleCondition(rule: RouterRule): RuleCondition {
  const when = rule.when;
  // Only missing, null or {} always matches; false, 0, "", [] or text are kept and refused.
  if (when === undefined || when === null || (isRecord(when) && Object.keys(when).length === 0)) return { form: "always" };
  const check = checkOf(when);
  if (!isRecord(when)) return { form: "custom", raw: when, check };
  const field = typeof when.field === "string" ? when.field : "";
  if (typeof when.operator === "string" && when.operator.trim()) {
    return { form: "operator", field, operator: when.operator, value: when.value, hasValue: "value" in when, check };
  }
  if (when.operator !== undefined && when.operator !== null && typeof when.operator !== "string") return { form: "custom", raw: when, check };
  if ("field" in when && Object.keys(when).every((key) => key === "field" || key === "operator" || key === "value")) {
    return { form: "operator", field, operator: "", value: when.value, hasValue: "value" in when, check };
  }
  return { form: "custom", raw: when, check };
}

// The value type of a saved value. Anything that cannot be edited as one of the types without
// changing it (objects, mixed lists, nested values) is "none" and is kept as it is.
export function valueTypeOf(value: unknown, operator: string): ValueType | "keep" {
  if (value === undefined || value === null || value === "") {
    if (value === "") return operatorValueTypes(operator).includes("text") ? "text" : operatorValueTypes(operator)[0] ?? "text";
    return operatorValueTypes(operator)[0] ?? "text";
  }
  if (typeof value === "string") return "text";
  if (typeof value === "number" && Number.isFinite(value)) return "number";
  if (typeof value === "boolean") return "boolean";
  if (Array.isArray(value)) {
    if (value.every((item) => typeof item === "string")) return "text_list";
    if (value.every((item) => typeof item === "number" && Number.isFinite(item))) return "number_list";
  }
  return "keep";
}

export function valueText(value: unknown, type: ValueType | "keep"): string {
  if (type === "keep") return JSON.stringify(value);
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.map(String).join("\n");
  return String(value);
}

// The typed value for what the author entered under an explicit type. The text is never guessed
// into another type: "5" stays text unless Number is chosen. Lists are one item per line, so a
// comma inside an item stays part of it. Returns null when the input is not valid for the type.
export function parseTypedValue(text: string, type: ValueType): { value: unknown } | null {
  if (type === "text") return { value: text };
  if (type === "number") {
    const trimmed = text.trim();
    if (!trimmed) return null;
    const number = Number(trimmed);
    return Number.isFinite(number) ? { value: number } : null;
  }
  if (type === "boolean") return text === "true" ? { value: true } : text === "false" ? { value: false } : null;
  if (type === "none") return { value: undefined };
  const items = text.split("\n").map((item) => item.trim()).filter(Boolean);
  if (type === "text_list") return { value: items };
  const numbers = items.map(Number);
  return numbers.every((item) => Number.isFinite(item)) ? { value: numbers } : null;
}

// Rule with a new condition part: the field, operator and value of `when`, other keys kept.
export function withCondition(rule: RouterRule, patch: { field?: string; operator?: string; value?: unknown }): RouterRule {
  const when: Record<string, unknown> = { ...(isRecord(rule.when) ? rule.when : {}) };
  if (patch.field !== undefined) when.field = patch.field;
  if (patch.operator !== undefined) when.operator = patch.operator;
  if ("value" in patch) {
    if (patch.value === undefined) delete when.value;
    else when.value = patch.value;
  }
  return { ...rule, when };
}

// Plain warnings of a rule. A rule the server cannot check blocks the whole step.
export function ruleWarnings(condition: RuleCondition): string[] {
  if (condition.form === "always") return ["This rule has no condition, so it always matches and the rules below it never run."];
  const warnings: string[] = [];
  if (condition.check.state === "invalid") {
    warnings.push(`This rule cannot be checked (${condition.check.reason}), so the workflow stops at this step with an error until it is fixed.`);
  } else if (condition.check.state === "uncertain") {
    warnings.push(`This editor cannot read this rule with certainty (${condition.check.reason}); the server decides when the workflow runs.`);
  }
  if (condition.form === "custom") warnings.push("This editor cannot show this condition; it is kept exactly as saved.");
  return warnings;
}
