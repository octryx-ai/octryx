// Workspace → Coding tools & devices, Connectors → MCP servers and Rules → Budget: the readers
// for /api/v1/admin/workspaces/{id}/coding|mcp-servers|budget and the typed command & file rules
// (agent_gateway_policy.tool_rules) the server validates.

export type RuleKind = "command_prefix_denied" | "command_argument_denied" | "command_requires_argument" | "path_denied";
export type ToolRule = { id: string; kind: RuleKind; prefix?: string[]; command?: string[]; argument?: string; tools?: string[]; glob?: string };
export type RoleCeiling = "read_only" | "edit" | "bypass";
export type RoleModes = Record<"viewer" | "member" | "owner" | "admin", RoleCeiling>;
export type Coding = { requiresGovernedRouting: boolean; toolRules: ToolRule[]; clientDeny: string[]; roleModes: RoleModes };

// What each role's coding sessions may do in this Workspace (agent_gateway_policy.role_modes).
export const DEFAULT_ROLE_MODES: RoleModes = { viewer: "read_only", member: "edit", owner: "bypass", admin: "bypass" };
export const ROLE_ROWS: { role: keyof RoleModes; label: string; desc: string }[] = [
  { role: "viewer", label: "Viewer", desc: "Workspace viewers, and anybody without a role" },
  { role: "member", label: "Member", desc: "Workspace members" },
  { role: "owner", label: "Owner", desc: "Workspace owners" },
  { role: "admin", label: "Platform admin", desc: "Platform admins who are not an owner here" },
];
export const CEILING_OPTIONS: { value: RoleCeiling; label: string }[] = [
  { value: "read_only", label: "Read only (questions, plans)" },
  { value: "edit", label: "Edit (Ask first, Accept edits)" },
  { value: "bypass", label: "Edit and Bypass" },
];
const CEILINGS = new Set<string>(["read_only", "edit", "bypass"]);

export function readRoleModes(value: unknown): RoleModes {
  const data = record(value);
  const pick = (role: keyof RoleModes): RoleCeiling =>
    CEILINGS.has(String(data[role])) ? (data[role] as RoleCeiling) : DEFAULT_ROLE_MODES[role];
  return { viewer: pick("viewer"), member: pick("member"), owner: pick("owner"), admin: pick("admin") };
}
export type McpServer = { name: string; allowed: boolean; reason: string };
export type Budget = { session_usd: number | null; request_usd: number | null; per_person_daily_usd: number | null };
export type BudgetView = Budget & { platform: Budget | null };
export type ToolVisibility = {
  source: "tool_policy" | "runtime_policy.tool_policy" | "none";
  allowlist: string[];
  denylist: string[];
  allowPatterns: string[];
  denyPatterns: string[];
  allowReadOnly: boolean;
};

export const RULE_KINDS: { kind: RuleKind; label: string; desc: string }[] = [
  { kind: "command_prefix_denied", label: "Command blocked", desc: "A command that starts with these words is refused." },
  { kind: "command_argument_denied", label: "Argument blocked", desc: "This command is refused when it carries the argument." },
  { kind: "command_requires_argument", label: "Argument required", desc: "This command is refused unless it carries the argument." },
  { kind: "path_denied", label: "Path blocked", desc: "Reading or writing files that match the pattern is refused." },
];

// The file tools a path rule covers; the baseline rules use the same set.
export const FILE_TOOLS = ["Read", "Edit", "Write", "MultiEdit"];

const KIND_SET = new Set(RULE_KINDS.map((item) => item.kind));
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
const record = (value: unknown): Record<string, unknown> => (value && typeof value === "object" ? value as Record<string, unknown> : {});

export function ruleKindLabel(kind: RuleKind): string {
  return RULE_KINDS.find((item) => item.kind === kind)?.label ?? kind;
}

export function ruleTarget(rule: ToolRule): string {
  if (rule.kind === "command_prefix_denied") return (rule.prefix ?? []).join(" ");
  if (rule.kind === "path_denied") return rule.glob ?? "";
  return `${(rule.command ?? []).join(" ")} ${rule.argument ?? ""}`.trim();
}

export function readCoding(payload: unknown): Coding | null {
  const data = record(payload);
  if (typeof data.requires_governed_routing !== "boolean" || !Array.isArray(data.tool_rules)) return null;
  const toolRules = data.tool_rules.map(record).filter((rule) => typeof rule.id === "string" && KIND_SET.has(rule.kind as RuleKind))
    .map((rule) => ({ ...rule, id: String(rule.id), kind: rule.kind as RuleKind }) as ToolRule);
  return { requiresGovernedRouting: data.requires_governed_routing, toolRules, clientDeny: strings(data.client_deny),
    roleModes: readRoleModes(data.role_modes) };
}

export function codingPayload(coding: Coding) {
  return { requires_governed_routing: coding.requiresGovernedRouting, tool_rules: coding.toolRules, client_deny: coding.clientDeny,
    role_modes: coding.roleModes };
}

const words = (text: string): string[] => text.trim().split(/\s+/).filter(Boolean);

// A stable rule id from what the rule says; a number is appended when the id is taken.
export function ruleId(kind: RuleKind, target: string, taken: string[]): string {
  const base = `${kind.split("_")[0]}-${target.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")}`.slice(0, 60) || kind;
  let id = base;
  for (let index = 2; taken.includes(id); index += 1) id = `${base}-${index}`;
  return id;
}

export type RuleDraft = { kind: RuleKind; command: string; argument: string; glob: string };

export function ruleDraftProblems(draft: RuleDraft): string[] {
  if (draft.kind === "path_denied") return draft.glob.trim() ? [] : ["Enter the path pattern."];
  const problems = words(draft.command).length ? [] : ["Enter the command."];
  if (draft.kind !== "command_prefix_denied" && (!draft.argument.trim() || /\s/.test(draft.argument.trim()))) {
    problems.push("Enter one argument without spaces.");
  }
  return problems;
}

export function ruleFromDraft(draft: RuleDraft, taken: string[]): ToolRule {
  const rule: Omit<ToolRule, "id"> = draft.kind === "command_prefix_denied" ? { kind: draft.kind, prefix: words(draft.command) }
    : draft.kind === "path_denied" ? { kind: draft.kind, tools: FILE_TOOLS, glob: draft.glob.trim() }
      : { kind: draft.kind, command: words(draft.command), argument: draft.argument.trim() };
  return { id: ruleId(draft.kind, ruleTarget({ id: "", ...rule }), taken), ...rule };
}

export function readMcpServers(payload: unknown): McpServer[] | null {
  const servers = record(payload).servers;
  if (!Array.isArray(servers)) return null;
  // Runtime's Workspace allow (GET …/workspaces/{id}/mcp-servers) names the server in ``server_name``.
  return servers.map(record).map((item): Record<string, unknown> => ({ ...item, name: item.server_name ?? item.name }))
    .filter((item) => typeof item.name === "string")
    .map((item) => ({ name: String(item.name), allowed: item.allowed === true, reason: typeof item.reason === "string" ? item.reason : "" }));
}

const amount = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

const readAmounts = (data: Record<string, unknown>): Budget => ({
  session_usd: amount(data.session_usd), request_usd: amount(data.request_usd), per_person_daily_usd: amount(data.per_person_daily_usd),
});

export function readBudget(payload: unknown): BudgetView | null {
  const data = record(payload);
  if (!("session_usd" in data)) return null;
  return { ...readAmounts(data), platform: data.platform && typeof data.platform === "object" ? readAmounts(record(data.platform)) : null };
}

const usd = (value: number | null) => (value === null ? "–" : value === 0 ? "no cap" : `$${value}`);

// The values an empty field inherits (settings review): shown, never as a placeholder.
export function platformBudgetText(platform: Budget | null): string {
  if (!platform) return "";
  return `Platform value: ${usd(platform.session_usd)} per session · ${usd(platform.request_usd)} per request · ${usd(platform.per_person_daily_usd)} per person/day`;
}

export function readToolVisibility(payload: unknown): ToolVisibility | null {
  const data = record(payload);
  const policy = record(data.policy);
  const source = data.source === "tool_policy" || data.source === "runtime_policy.tool_policy" ? data.source : data.source === "none" ? "none" : null;
  if (!source) return null;
  return {
    source, allowlist: strings(policy.allowlist), denylist: strings(policy.denylist), allowPatterns: strings(policy.allow_patterns),
    denyPatterns: strings(policy.deny_patterns), allowReadOnly: policy.allow_read_only === true,
  };
}

// One line for the Rules table: what the tool policy the dispatch enforces does here.
export function toolVisibilityText(view: ToolVisibility): string {
  const parts: string[] = [];
  if (view.allowlist.length || view.allowPatterns.length) {
    parts.push(`Only ${[...view.allowlist, ...view.allowPatterns].join(", ")}`);
  }
  if (view.allowReadOnly) parts.push("read-only tools allowed");
  if (view.denylist.length || view.denyPatterns.length) parts.push(`hidden: ${[...view.denylist, ...view.denyPatterns].join(", ")}`);
  return parts.length ? parts.join(" · ") : "Every tool the platform offers";
}

// An input's text → the stored amount: empty = inherit (null); anything else must be a number ≥ 0.
export function budgetAmount(text: string): number | null | "invalid" {
  if (!text.trim()) return null;
  const value = Number(text);
  return Number.isFinite(value) && value >= 0 ? value : "invalid";
}

export function settingsErrorText(error: unknown): string {
  const detail = (error as { detail?: { reason?: unknown; path?: unknown } }).detail;
  if ((error as { status?: number }).status === 403) {
    const reason = typeof detail?.reason === "string" ? detail.reason : "";
    return (error as { code?: string }).code === "platform_admin_required" || reason
      ? `Not saved: only a platform admin can loosen this${reason ? ` (${reason})` : ""}.`
      : "Only the Workspace's admins can change this.";
  }
  const reason = typeof detail?.reason === "string" && detail.reason ? detail.reason.replace(/_/g, " ") : "";
  const path = typeof detail?.path === "string" && detail.path ? ` (${detail.path})` : "";
  return reason ? `Not saved: ${reason}${path}.` : "The change could not be saved.";
}
