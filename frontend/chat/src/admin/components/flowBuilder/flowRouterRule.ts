// If / else step rule shape and the branch name a rule picks or is given.

export type RouterRule = {
  route?: unknown;
  target?: unknown;
  when?: unknown;
  [key: string]: unknown;
};

// The branch a matching rule picks, exactly like dag_executor: `route or target or "default"`.
export function ruleBranch(rule: RouterRule): string {
  return String(rule.route || rule.target || "default");
}

// Writes a branch name into the key the rule already uses (`route`, else an existing `target`).
export function withRuleBranch(rule: RouterRule, name: string): RouterRule {
  return "route" in rule || !("target" in rule) ? { ...rule, route: name } : { ...rule, target: name };
}
