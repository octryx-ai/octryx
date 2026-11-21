import { checkDetail, type DeniedRule, type EffectiveRules, type PolicyDenial, type ToolRuleDenial } from "./codingRulesApi";

// Coding rules as one compact table, never raw rule strings: every rule that limits
// the coding agent in one row, What / Rule / Applies to / Source, in words. A rule the server lists more than once
// (the same rule from the baseline and the Workspace, or as a published policy) is one row naming each source.
// Pure: no React.

export type RuleEditPlace = "workspaceCoding" | "cedarPolicies" | "policies" | "approvalRule" | "pipeline";

// The rule in words; a command, an argument or a pattern is a code part, shown in mono.
export type RulePart = string | { code: string };

export type CodingRuleRow = {
  key: string;
  what: string;
  rule: RulePart[];
  // The pattern behind a rule said in words ("Any .env file" for `**/.env`), for the row's tooltip.
  pattern?: string;
  appliesTo: string;
  sources: string[];
  edit: RuleEditPlace;
  // The Workspace command & file rules behind a tool-rule row (their ids in Workspace settings › Coding), so the row
  // can be changed or removed here; empty for every other row.
  ruleIds?: string[];
  // A rule that blocks; the others ask for an approval or a check.
  tone: "block" | "approval" | "check" | "neutral";
};

/** The rule as plain text ("git push with --force"). */
export function ruleText(parts: RulePart[]): string {
  return parts.map((part) => (typeof part === "string" ? part : part.code)).join(" ");
}

const ACTION_WORDS: Record<string, string> = { run_command: "Commands", write_path: "Changing files", read_path: "Reading files" };
const FILE_EDIT_TOOLS = new Set(["Edit", "Write", "MultiEdit", "NotebookEdit"]);

/** Who a path rule stops, in words: the file tools it names. */
export function fileToolsText(tools: string[]): string {
  const reads = tools.includes("Read");
  const edits = tools.some((tool) => FILE_EDIT_TOOLS.has(tool));
  if (reads && edits) return "Reading and changing files";
  if (edits) return "Changing files";
  if (reads) return "Reading files";
  return tools.join(", ") || "Files";
}

/**
 * A path pattern in words where it has a common shape; otherwise the pattern itself.
 * `**∕.env` → "Any .env file", `**∕.aws/**` → "Anything in an .aws folder", `~/.aws/**` → "Anything in ~/.aws",
 * `**∕*.pem` → "Any .pem file".
 */
export function globText(glob: string): string {
  const pattern = glob.trim();
  let match = /^\*\*\/([^*/?[\]]+)\/\*\*$/.exec(pattern);
  if (match) return `Anything in ${/^[aeiou.]/i.test(match[1]) ? "an" : "a"} ${match[1]} folder`;
  match = /^(~?\/?[^*?[\]]+)\/\*\*$/.exec(pattern);
  if (match) return `Anything in ${match[1]}`;
  match = /^\*\*\/\*(\.[^*/?[\]]+)$/.exec(pattern);
  if (match) return `Any ${match[1]} file`;
  match = /^\*\*\/([^*/?[\]]+)$/.exec(pattern);
  if (match) return `Any ${match[1]} file`;
  match = /^\*\*\/([^/?[\]]+)$/.exec(pattern);
  if (match) return `Any file named ${match[1]}`;
  return pattern;
}

function toolRuleRow(rule: ToolRuleDenial): CodingRuleRow {
  const { command, argument } = rule;
  const sources = [rule.origin === "workspace" ? "Workspace" : "Built-in"];
  if (typeof rule.published_version === "number") sources.push(`Policy v${rule.published_version}`);
  const base = { key: `tool:${rule.id}`, sources, edit: "workspaceCoding" as const, tone: "block" as const,
    ruleIds: rule.origin === "baseline" ? [] : rule.ids };
  if (rule.kind === "path_denied") {
    const glob = rule.glob;
    const words = globText(glob);
    return { ...base, what: "Path blocked", rule: words === glob ? [{ code: glob }] : [words], pattern: words === glob ? undefined : glob,
      appliesTo: fileToolsText(rule.tools) };
  }
  if (rule.kind === "command_argument_denied") {
    return { ...base, what: "Argument blocked", rule: [{ code: command }, "with", { code: argument }], appliesTo: "Commands" };
  }
  if (rule.kind === "command_requires_argument") {
    return { ...base, what: "Argument required", rule: [{ code: command }, "only with", { code: argument }], appliesTo: "Commands" };
  }
  return { ...base, what: "Command blocked", rule: [{ code: command }], appliesTo: "Commands" };
}

function policyRow(rule: PolicyDenial): CodingRuleRow {
  const commands = rule.actions.includes("run_command");
  const files = rule.actions.some((action) => action !== "run_command");
  return {
    key: `policy:${rule.id}`,
    what: commands && files ? "Action blocked" : commands ? "Command blocked" : "Path blocked",
    rule: [rule.title],
    appliesTo: rule.actions.map((action) => ACTION_WORDS[action] ?? action).join(", "),
    sources: [typeof rule.version === "number" ? `Policy v${rule.version}` : "Policy"],
    edit: "cedarPolicies",
    tone: "block",
  };
}

function deniedRow(rule: DeniedRule): CodingRuleRow {
  return rule.source === "tool_rule" ? toolRuleRow(rule) : policyRow(rule);
}

/** One row per rule: rows that say the same (what, rule, applies to) collapse and keep every source once. */
export function collapseRows(rows: CodingRuleRow[]): CodingRuleRow[] {
  const byText = new Map<string, CodingRuleRow>();
  for (const row of rows) {
    const key = [row.what, ruleText(row.rule), row.pattern ?? "", row.appliesTo].join("\u0000").toLowerCase();
    const same = byText.get(key);
    if (!same) byText.set(key, { ...row, sources: [...row.sources], ruleIds: row.ruleIds ? [...row.ruleIds] : undefined });
    else {
      for (const source of row.sources) if (!same.sources.includes(source)) same.sources.push(source);
      for (const id of row.ruleIds ?? []) {
        same.ruleIds = same.ruleIds ?? [];
        if (!same.ruleIds.includes(id)) same.ruleIds.push(id);
      }
    }
  }
  // Array.from, not a spread: the unit-test loaders transpile to ES5, where a spread drops a Map iterator.
  return Array.from(byText.values());
}

const CHECK_EFFECTS: Record<string, string> = { warn: "warns", review: "asks for a review", block: "blocks" };

/** Every rule of the page, blocked actions first, then approvals, who approves and the checks. */
export function codingRuleRows(rules: EffectiveRules): CodingRuleRow[] {
  const denied = collapseRows(rules.denied.map(deniedRow));
  const approvals: CodingRuleRow[] = rules.needs_approval.items.map((entry) => ({
    key: `approval:${entry.kind}:${entry.value}`,
    what: "Needs approval",
    rule: entry.kind === "risk" ? [`Every tool of risk "${entry.value}"`] : [{ code: entry.value }],
    appliesTo: "Tool calls",
    sources: ["Tool & approval policies"],
    edit: "policies",
    tone: "approval",
  }));
  const fourEyes = rules.who_approves.rule !== "single_admin";
  const approver: CodingRuleRow = {
    key: "approver",
    what: "Who approves",
    rule: [fourEyes ? "Four eyes: nobody approves their own request" : "Single admin: an admin may approve their own request"],
    appliesTo: "Plans, CI actions, policy changes",
    sources: ["Approval rule"],
    edit: "approvalRule",
    tone: "neutral",
  };
  const checks: CodingRuleRow[] = rules.checks.items.map((check, index) => ({
    key: `check:${check.pipeline ?? ""}:${check.key ?? index}`,
    what: "Check",
    rule: [`${check.label}: ${checkDetail(check)}`],
    appliesTo: `Every change, ${CHECK_EFFECTS[check.effect] ?? check.effect}`,
    sources: [check.pipeline ? `Delivery pipeline (${check.pipeline})` : "Delivery pipeline"],
    edit: "pipeline",
    tone: "check",
  }));
  return [...denied, ...collapseRows(approvals), approver, ...checks];
}
