// Display-only labels for the connections out of an If / else step. They are derived on
// every render from the saved rules and connection conditions and live only on the canvas edge
// (`label`, `ariaLabel`, `className`); `toDefinitionEdge` never reads them, so nothing is stored.
//
// The wording follows the runtime: rules are checked in order and the first match picks its
// branch, otherwise `default_route` (dag_executor._execute_router_node); a connection runs for the
// chosen branch when its condition names it (router_branches.py); a connection without a
// condition is the fallback. Where a label cannot be certain it says so instead of guessing:
// - a string condition `c` runs for a branch named `c` and, when it starts with `route:`, also for
//   the branch named after the prefix, so both names count;
// - a rule or custom condition whose shape the evaluator cannot decide (refuses such a step)
//   makes the whole step "Needs configuration"; nothing after it is called "Never taken";
// - a branch several cases share names every case.
import { edgeBranch, matchedBranchNames } from "./flowBranchConnections";
import { ruleBranch, type RouterRule } from "./flowRouterRule";
import { conditionShape, isRecord, LIST_OPERATORS, NUMBER_OPERATORS, rulesState, type ConditionShape } from "./flowConditionShape";

export type BranchLabelKind = "rule" | "otherwise" | "shared" | "fallback" | "custom" | "never" | "invalid";

export type BranchLabel = { kind: BranchLabelKind; text: string; full: string };

type NodeLike = { id: string; type?: string; config?: Record<string, unknown> };
type EdgeLike = { id: string; source: string; condition: unknown };

// Longest label drawn on a line; the full wording stays in the accessible name.
export const MAX_LABEL_LENGTH = 34;

const SYMBOLS: Record<string, string> = {
  equals: "=", eq: "=", "==": "=", not_equals: "≠", neq: "≠", "!=": "≠",
  gt: ">", gte: "≥", lt: "<", lte: "≤", in: "is one of", not_in: "is not one of",
  contains: "contains", not_contains: "does not contain",
};
// The saved operand as written: a list is spelled out only for "is one of"; any other list, object
// or null is shown as saved JSON, so no type is implied that the rule does not state.
function formatValue(value: unknown, operator: string): string {
  if (NUMBER_OPERATORS.has(operator) && typeof value === "string") return value.trim();
  if (typeof value === "string") return `“${value}”`;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (LIST_OPERATORS.has(operator) && Array.isArray(value) && value.every((item) => typeof item === "string" || typeof item === "number")) {
    return value.map((item) => (typeof item === "string" ? `“${item}”` : String(item))).join(", ");
  }
  return JSON.stringify(value) ?? "a custom value";
}

// One decidable comparison in a few words.
export function comparisonSummary(shape: Extract<ConditionShape, { state: "ok" }>): string {
  const { field, operator, value } = shape;
  // exists: the value is (not) null/missing. truthy: Python truthiness, so empty, 0 and false all
  // count as "no".
  if (operator === "exists") return value ? `${field} is present` : `${field} is missing`;
  if (operator === "truthy") return value ? `${field} is not empty, 0 or false` : `${field} is empty, 0 or false`;
  return `${field} ${SYMBOLS[operator]} ${formatValue(value, operator)}`;
}

function shorten(text: string): string {
  return text.length > MAX_LABEL_LENGTH ? `${text.slice(0, MAX_LABEL_LENGTH - 1).trimEnd()}…` : text;
}

type Case = { order: number; kind: "rule" | "otherwise"; text: string; short: string; branch: string };

type RouterReading =
  | { state: "invalid"; reason: string }
  | { state: "uncertain"; reason: string }
  | { state: "ok"; rules: { branch: string; text: string; order: number }[]; reachableUntil: number; defaultRoute: string; defaultReachable: boolean };

// The router's rules as the runtime reads them, or why they cannot be read with certainty.
function readRouter(router: NodeLike): RouterReading {
  const raw = router.config?.routes;
  const defaultRoute = String(router.config?.default_route || "default");
  // An invalid rule anywhere refuses the step; otherwise an uncertain one leaves the order unknown.
  const state = rulesState(raw);
  if (state.state !== "ok") return state;
  const rules: { branch: string; text: string; order: number }[] = [];
  let reachableUntil = Number.POSITIVE_INFINITY;
  for (const [index, rule] of ((raw as unknown[]) ?? []).entries()) {
    const shape = conditionShape(isRecord(rule) ? rule.when : rule);
    if (shape.state !== "ok" && shape.state !== "always") continue;
    const lead = index === 0 ? "If" : "Else if";
    rules.push({ branch: ruleBranch(rule as RouterRule), text: shape.state === "always" ? `${lead} always` : `${lead} ${comparisonSummary(shape)}`, order: index });
    if (shape.state === "always" && reachableUntil === Number.POSITIVE_INFINITY) reachableUntil = index;
  }
  return { state: "ok", rules, reachableUntil, defaultRoute, defaultReachable: reachableUntil === Number.POSITIVE_INFINITY };
}

function casesFor(names: string[], reading: Extract<RouterReading, { state: "ok" }>): Case[] {
  const wanted = new Set(names);
  const cases: Case[] = reading.rules
    .filter((rule) => rule.order <= reading.reachableUntil && wanted.has(rule.branch))
    .map((rule) => ({ order: rule.order, kind: "rule" as const, text: rule.text, short: `Rule ${rule.order + 1}`, branch: rule.branch }));
  if (reading.defaultReachable && wanted.has(reading.defaultRoute)) {
    cases.push({ order: Number.POSITIVE_INFINITY, kind: "otherwise", text: "Otherwise", short: "Otherwise", branch: reading.defaultRoute });
  }
  return cases;
}

function quoted(names: string[]): string {
  return names.map((name) => `“${name}”`).join(" or ");
}

export function branchEdgeLabel(router: NodeLike, condition: unknown): BranchLabel {
  const reading = readRouter(router);
  if (reading.state === "invalid") {
    return { kind: "invalid", text: "Needs configuration", full: `Needs configuration: ${reading.reason}. This If / else step cannot run until it is fixed.` };
  }
  if (reading.state === "uncertain") {
    return { kind: "custom", text: "Uncertain rule", full: `Uncertain: ${reading.reason}. The server decides when the workflow runs.` };
  }
  const branch = edgeBranch(condition);
  if (branch.kind === "fallback") {
    const text = "Any other branch";
    return { kind: "fallback", text, full: `${text}: runs when no other connection matches` };
  }
  if (branch.kind === "never") return { kind: "never", text: "Never matches", full: `Never matches: ${branch.text}` };
  const names = matchedBranchNames(condition);
  if (names === null) {
    const shape = conditionShape(condition);
    if (shape.state === "invalid") {
      return { kind: "invalid", text: "Needs configuration", full: `Needs configuration: this connection's condition ${shape.reason}.` };
    }
    if (shape.state === "uncertain") {
      return { kind: "custom", text: "Custom condition", full: `Custom condition, uncertain (${shape.reason}); the server decides when the workflow runs.` };
    }
    return { kind: "custom", text: "Custom condition", full: `Custom condition, decided when the workflow runs: ${branch.kind === "custom" ? branch.text : ""}` };
  }
  const cases = casesFor(names, reading);
  if (!cases.length) {
    const text = "Never taken";
    return { kind: "never", text, full: `${text}: no rule picks branch ${quoted(names)}` };
  }
  // Name only the branches that actually exist; a route:-prefixed condition may match one or both.
  const full = `${cases.map((item) => item.text).join(" or ")} (branch ${quoted([...new Set(cases.map((item) => item.branch))])})`;
  if (cases.length === 1) return { kind: cases[0].kind, text: shorten(cases[0].text), full };
  // Shared branch: name every case, compactly, never just "Otherwise".
  const joined = cases.map((item) => item.text).join(" or ");
  const compact = cases.map((item) => item.short).join(cases.length === 2 ? " or " : ", ");
  return { kind: "shared", text: joined.length <= MAX_LABEL_LENGTH ? joined : shorten(compact), full };
}

// Labels for every connection that leaves an If / else step, keyed by edge id.
export function branchEdgeLabels(nodes: NodeLike[], edges: EdgeLike[]): Map<string, BranchLabel> {
  const routers = new Map(nodes.filter((node) => node.type === "router").map((node) => [node.id, node]));
  const labels = new Map<string, BranchLabel>();
  for (const edge of edges) {
    const router = routers.get(edge.source);
    if (router) labels.set(edge.id, branchEdgeLabel(router, edge.condition));
  }
  return labels;
}

// The canvas edges with their display labels; unlabelled edges are returned unchanged.
export function withBranchLabels<E extends { id: string; className?: string }>(edges: E[], labels: Map<string, BranchLabel>): E[] {
  return edges.map((edge) => {
    const label = labels.get(edge.id);
    if (!label) return edge;
    return {
      ...edge,
      label: label.text,
      ariaLabel: `Connection for ${label.full}`,
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 4,
      className: [edge.className, "flow-edge--branch", `flow-edge--branch-${label.kind}`].filter(Boolean).join(" "),
    };
  });
}
