// If / else step branches and connections: which branch a connection runs for and whether every branch is covered.
import { conditionShape, isRecord, rulesState } from "./flowConditionShape";
import { ruleBranch } from "./flowRouterRule";

export type EdgeLike = {
  id?: string;
  source_node_id?: string;
  from_node_id?: string;
  target_node_id?: string;
  to_node_id?: string;
  condition?: unknown;
};

export type EdgeBranch =
  | { kind: "branch"; name: string }
  | { kind: "fallback" }
  | { kind: "custom"; text: string }
  | { kind: "never"; text: string };

// Which branch a connection's condition selects, in the forms the runtime accepts
// (flow_orchestration/router_branches.py): an empty (falsy) condition is the explicit fallback; a
// string or an object with a `route` key names a branch; any other object is a custom predicate
// that only the run can decide; any other value never matches.
export function edgeBranch(condition: unknown): EdgeBranch {
  if (condition === undefined || condition === null || condition === "" || condition === false || condition === 0) return { kind: "fallback" };
  if (typeof condition === "string") {
    return { kind: "branch", name: condition.startsWith("route:") ? condition.slice("route:".length) : condition };
  }
  if (Array.isArray(condition)) return condition.length === 0 ? { kind: "fallback" } : { kind: "never", text: JSON.stringify(condition) };
  if (typeof condition === "object") {
    if (Object.keys(condition).length === 0) return { kind: "fallback" };
    if ("route" in condition) {
      const route = (condition as { route: unknown }).route;
      return { kind: "branch", name: route === undefined || route === null ? "" : String(route) };
    }
    // `{field: "route", operator: "equals", value: X}` compares the chosen branch exactly; recognised for
    // display, written back only when the author picks a branch.
    const record = condition as Record<string, unknown>;
    if (record.field === "route") {
      const operator = typeof record.operator === "string" ? record.operator.trim().toLowerCase() : "";
      if (["equals", "eq", "=="].includes(operator) && typeof record.value === "string" && Object.keys(record).length === 3) {
        return { kind: "branch", name: record.value };
      }
    }
    return { kind: "custom", text: JSON.stringify(condition) };
  }
  return { kind: "never", text: JSON.stringify(condition) };
}

// Every saved branch name a connection condition runs for (router_branches._branches_selected_by):
// a string `c` runs for the branch named `c` and, when it starts with `route:`, also for the
// branch named after the prefix. Null for a custom predicate, empty when it never matches.
export function matchedBranchNames(condition: unknown): string[] | null {
  if (typeof condition === "string") {
    return condition.startsWith("route:") ? [condition, condition.slice("route:".length)] : [condition];
  }
  const branch = edgeBranch(condition);
  if (branch.kind === "branch") return [branch.name];
  if (branch.kind === "custom") return null;
  return [];
}

// The condition the edge editor writes for a chosen branch ("" = no condition, the fallback).
export function branchCondition(choice: EdgeBranch): string {
  return choice.kind === "branch" ? `route:${choice.name}` : "";
}

export type BranchSummary = {
  name: string;
  label: string;
  targets: string[];
  // False after a rule without a condition: that rule always matches, so this branch is never picked.
  reachable: boolean;
};

// What happens when the step picks a branch with no connection of its own: with a
// connection that has no branch, that connection runs; otherwise the run fails at this step
// (`router_branch_unmatched`) and nothing after it runs. A step without connections ends the flow.
export type BranchCoverage =
  | { state: "no_connections" }
  | { state: "complete" }
  | { state: "missing"; branches: string[] }
  // A custom connection condition may or may not pick these branches; only the run can tell.
  | { state: "runtime"; branches: string[] }
  // A rule or connection condition the server cannot check: the step does not run at all.
  | { state: "blocked"; reason: string };

export type BranchConnections = {
  branches: BranchSummary[];
  fallbackTargets: string[];
  customTargets: string[];
  // Custom connection conditions the server cannot check (router_condition_invalid).
  invalidCustomTargets: string[];
  neverTargets: string[];
  // Connections whose branch names no reachable rule or the Otherwise branch picks.
  // `names`: every branch name the condition could run for (two for a route:-prefixed string).
  orphanTargets: { names: string[]; target: string }[];
  coverage: BranchCoverage;
};

const edgeSource = (edge: EdgeLike) => edge.source_node_id ?? edge.from_node_id ?? "";
const edgeTarget = (edge: EdgeLike) => edge.target_node_id ?? edge.to_node_id ?? "";

// `rules` are the saved `routes` items as they are; only rule objects name branches.
export function branchConnections(
  nodeId: string,
  rules: unknown[],
  defaultRoute: string,
  edges: EdgeLike[],
  nodeName: (id: string) => string = (id) => id,
): BranchConnections {
  const outgoing = edges.filter((edge) => edgeSource(edge) === nodeId);
  // Branches in rule order, like router_branches.declared_router_branches: everything after a
  // rule without a condition (missing, null or {} only), including Otherwise, is never picked.
  const branches: BranchSummary[] = [];
  let reachable = true;
  const add = (name: string, label: string) => {
    const existing = branches.find((item) => item.name === name);
    if (existing) {
      existing.label = `${existing.label} and ${label}`;
      existing.reachable ||= reachable;
    } else {
      branches.push({ name, label, targets: [], reachable });
    }
  };
  rules.forEach((rule, index) => {
    if (!isRecord(rule)) return;
    add(ruleBranch(rule), `Rule ${index + 1}`);
    if (conditionShape(rule.when).state === "always") reachable = false;
  });
  add(defaultRoute, "Otherwise");

  const result: BranchConnections = {
    branches, fallbackTargets: [], customTargets: [], invalidCustomTargets: [], neverTargets: [], orphanTargets: [], coverage: { state: "complete" },
  };
  for (const edge of outgoing) {
    const target = nodeName(edgeTarget(edge));
    const branch = edgeBranch(edge.condition);
    if (branch.kind === "fallback") result.fallbackTargets.push(target);
    else if (branch.kind === "never") result.neverTargets.push(target);
    else if (branch.kind === "custom") {
      (conditionShape(edge.condition).state === "invalid" ? result.invalidCustomTargets : result.customTargets).push(target);
    } else {
      // Every declared branch the condition can run for (a route:foo string also runs for "foo").
      const names = matchedBranchNames(edge.condition) ?? [branch.name];
      const matched = branches.filter((item) => item.reachable && names.includes(item.name));
      matched.forEach((item) => item.targets.push(target));
      if (!matched.length) result.orphanTargets.push({ names, target });
    }
  }
  const stepRules = rulesState(rules);
  const unconnected = branches.filter((item) => item.reachable && !item.targets.length).map((item) => item.name);
  if (stepRules.state === "invalid") result.coverage = { state: "blocked", reason: stepRules.reason };
  else if (result.invalidCustomTargets.length) result.coverage = { state: "blocked", reason: "a connection's condition cannot be checked" };
  else if (!outgoing.length) result.coverage = { state: "no_connections" };
  else if (result.fallbackTargets.length || !unconnected.length) result.coverage = { state: "complete" };
  else if (result.customTargets.length) result.coverage = { state: "runtime", branches: unconnected };
  else result.coverage = { state: "missing", branches: unconnected };
  return result;
}
