import { readJson } from "../../../admin/utils/adminPanelHelpers";

// Coding → Effective rules: everything that limits the coding agent in one Workspace, read only.

type DeniedBase = { id: string; title: string; actions: string[]; detail: string; edit: string };
// A published Cedar policy that forbids a coding action; `version`: its policy set version.
export type PolicyDenial = DeniedBase & { source: "policy"; version: number | null };
// A Workspace tool rule: its parts, the ids it collapses and where it comes from
// (`secure_work/coding/effective_rules.py`).
export type ToolRuleDenial = DeniedBase & { source: "tool_rule"; kind: string; command: string; argument: string;
  glob: string; tools: string[]; ids: string[]; origin: "baseline" | "workspace"; published_version: number | null };
export type DeniedRule = PolicyDenial | ToolRuleDenial;
export type PipelineCheck = { key: string; type: string; label: string; effect: "warn" | "review" | "block";
  rule: Record<string, unknown>; pipeline?: string };
export type EffectiveRules = {
  project_id: string;
  denied: DeniedRule[];
  needs_approval: { items: Array<{ kind: "risk" | "tool"; value: string }>; exempt_tools: string[]; edit: string };
  who_approves: { rule: string; edit: string };
  checks: { items: PipelineCheck[]; edit: string };
};

export function loadEffectiveRules(workspaceId: string): Promise<EffectiveRules> {
  return readJson<EffectiveRules>(`/api/v1/secure-work/workspaces/${encodeURIComponent(workspaceId)}/coding-rules`);
}

export const CHECK_TYPES: Record<string, string> = {
  pr_size_threshold: "PR size",
  file_line_threshold: "File size",
  test_requirement: "Test evidence",
  documentation_requirement: "Docs touched",
  branch_commit_naming: "Branch naming",
  dependency_change: "Dependency change",
};

const ACTION_WORDS: Record<string, string> = { write_path: "writes", read_path: "reads", run_command: "commands" };

export function actionsText(actions: string[]): string {
  return actions.map((action) => ACTION_WORDS[action] ?? action).join(", ");
}

/** What a check asks for, in one line (its rule's main setting). */
export function checkDetail(check: PipelineCheck): string {
  const rule = check.rule || {};
  const number = (key: string) => (typeof rule[key] === "number" ? Number(rule[key]) : null);
  if (check.type === "pr_size_threshold" && number("max_changed_lines") !== null) {
    return `More than ${number("max_changed_lines")} changed lines`;
  }
  if (check.type === "file_line_threshold" && number("max_file_lines") !== null) return `Files over ${number("max_file_lines")} lines`;
  if (check.type === "branch_commit_naming" && typeof rule.branch_pattern === "string") return rule.branch_pattern;
  if (check.type === "test_requirement") return "The repository's test command ran green in this session";
  if (check.type === "documentation_requirement") return "Docs change with the code";
  if (check.type === "dependency_change") return "Build files changed";
  return CHECK_TYPES[check.type] ?? check.type;
}

export const EFFECT_TONES: Record<string, string> = { warn: "neutral", review: "attention", block: "danger" };
