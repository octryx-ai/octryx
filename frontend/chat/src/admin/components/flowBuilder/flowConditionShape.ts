// The one reading of a saved If / else condition that the graph labels and the inspector share.
// It follows the server's final rule validation (conditional_rules.py) closely
// enough to never certify what the server refuses, without being a second validator: the server
// stays the authority, and a shape this editor cannot judge is "uncertain", not "invalid".
// - missing, null or {}: always matches; any other non-object (false, 0, "", [], text) is refused;
// - a comparison is `{field, operator, value}`; operators ignore case and surrounding spaces;
//   aliases eq/==/neq/!= are accepted;
// - exists/truthy need yes/no, in/not_in a list, comparisons a finite number; equality and
//   contains accept any present value.

export const SUPPORTED_OPERATORS = new Set([
  "equals", "eq", "==", "not_equals", "neq", "!=", "contains", "not_contains", "in", "not_in", "gt", "gte", "lt", "lte", "exists", "truthy",
]);
export const BOOLEAN_OPERATORS = new Set(["exists", "truthy"]);
export const LIST_OPERATORS = new Set(["in", "not_in"]);
export const NUMBER_OPERATORS = new Set(["gt", "gte", "lt", "lte"]);

export type ConditionShape =
  | { state: "always" }
  | { state: "invalid"; reason: string }
  // A shape this editor cannot judge with confidence; the server decides when the workflow runs.
  | { state: "uncertain"; reason: string }
  | { state: "ok"; field: string; operator: string; value: unknown };

export const isRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value);

// The spelling the server compares with: trimmed, lower case.
export const normalizeOperator = (operator: string) => operator.trim().toLowerCase();

// Python float() syntax for ASCII text: optional sign, digits with single underscores between
// them, an optional fraction and exponent, surrounding whitespace. Hex, binary, "Infinity" and
// other JavaScript-only forms do not match.
const PY_DIGITS = String.raw`\d(?:_?\d)*`;
const PY_FLOAT = new RegExp(String.raw`^\s*[+-]?(?:${PY_DIGITS}(?:\.(?:${PY_DIGITS})?)?|\.${PY_DIGITS})(?:[eE][+-]?${PY_DIGITS})?\s*$`);

// A number threshold the evaluator compares meaningfully (conditional_rules._finite_number): a
// finite number, never a boolean, or text Python reads as a finite number. Non-ASCII text that
// Python might still read (other digit scripts) is left to the server.
export function numberOperand(value: unknown): "ok" | "invalid" | "uncertain" {
  if (typeof value === "number") return Number.isFinite(value) ? "ok" : "invalid";
  if (typeof value !== "string") return "invalid";
  if (PY_FLOAT.test(value)) return Number.isFinite(Number(value.replace(/_/g, "").trim())) ? "ok" : "invalid";
  return isAscii(value) ? "invalid" : "uncertain";
}

function isAscii(text: string): boolean {
  for (let index = 0; index < text.length; index += 1) {
    if (text.charCodeAt(index) > 0x7f) return false;
  }
  return true;
}

function operandProblem(operator: string, value: unknown, present: boolean): ConditionShape | null {
  if (BOOLEAN_OPERATORS.has(operator)) return typeof value === "boolean" ? null : { state: "invalid", reason: "needs yes or no" };
  if (!present) return { state: "invalid", reason: "needs a value" };
  if (LIST_OPERATORS.has(operator)) return Array.isArray(value) ? null : { state: "invalid", reason: "needs a list" };
  if (NUMBER_OPERATORS.has(operator)) {
    const number = numberOperand(value);
    if (number === "invalid") return { state: "invalid", reason: "needs a finite number" };
    if (number === "uncertain") return { state: "uncertain", reason: "a number written in a form this editor cannot read" };
  }
  return null;
}

// How a rule's `when` (or a custom connection condition) reads. `operator` in the result is the
// normalised spelling; callers that edit keep the saved spelling themselves.
export function conditionShape(when: unknown): ConditionShape {
  if (when === undefined || when === null || (isRecord(when) && Object.keys(when).length === 0)) return { state: "always" };
  if (!isRecord(when)) return { state: "invalid", reason: "the condition is not a comparison" };
  const field = typeof when.field === "string" ? when.field.trim() : "";
  if (!field) return { state: "invalid", reason: "no value to check" };
  if (when.operator !== undefined && when.operator !== null && typeof when.operator !== "string") {
    return { state: "invalid", reason: "unsupported comparison" };
  }
  const operator = normalizeOperator(String(when.operator ?? ""));
  if (!operator) return { state: "invalid", reason: "no comparison" };
  if (!SUPPORTED_OPERATORS.has(operator)) return { state: "invalid", reason: "unsupported comparison" };
  return operandProblem(operator, when.value, "value" in when) ?? { state: "ok", field, operator, value: when.value };
}

export type RulesState = { state: "ok" } | { state: "invalid"; reason: string } | { state: "uncertain"; reason: string };

// Whether a step's rules can run: the server refuses the whole step when any rule is invalid
// (router_rule_invalid); an uncertain rule leaves it to the server.
export function rulesState(routes: unknown): RulesState {
  if (routes === undefined || routes === null) return { state: "ok" };
  if (!Array.isArray(routes)) return { state: "invalid", reason: "its rules are not a list" };
  let uncertain: string | null = null;
  for (const [index, rule] of routes.entries()) {
    if (!isRecord(rule)) return { state: "invalid", reason: `rule ${index + 1} is not a rule` };
    const shape = conditionShape(rule.when);
    if (shape.state === "invalid") return { state: "invalid", reason: `rule ${index + 1}: ${shape.reason}` };
    if (shape.state === "uncertain") uncertain ??= `rule ${index + 1}: ${shape.reason}`;
  }
  return uncertain ? { state: "uncertain", reason: uncertain } : { state: "ok" };
}
