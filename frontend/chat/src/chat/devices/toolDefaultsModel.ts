export const TOOL_DEFAULT_KEYS = [
  "unknown_tools", "web_tools", "shell", "path_rules", "device_models", "network", "browser",
] as const;
export type ToolDefaultKey = (typeof TOOL_DEFAULT_KEYS)[number];
export type ToolDefaults = Record<ToolDefaultKey, string> & { allowed_tools: string[] };

// The server's limits (device_runs_keys: MAX_ALLOWED_TOOLS, MAX_TOOL_NAME_CHARS).
export const MAX_ALLOWED_TOOLS = 100;
export const MAX_TOOL_NAME_CHARS = 200;

export type ToolDefaultOption = { value: string; label: string };
export type ToolDefaultRow = {
  key: ToolDefaultKey;
  label: string;
  words: string;
  help: string;
  options: ToolDefaultOption[];
};

export const TOOL_DEFAULT_ROWS: ToolDefaultRow[] = [
  {
    key: "unknown_tools", label: "Tools without a rule", words: "tools without a rule",
    help: "Deny: a tool no rule names is refused, except the tools listed below.",
    options: [{ value: "allow", label: "Allow and log" }, { value: "deny", label: "Deny" }],
  },
  {
    key: "web_tools", label: "Web search and fetch", words: "web search and fetch",
    help: "Research phases only: other phases cannot search or fetch web pages. Off: no phase can.",
    options: [{ value: "all", label: "Every phase" }, { value: "research_only", label: "Research phases only" },
      { value: "off", label: "Off" }],
  },
  {
    key: "shell", label: "Shell commands", words: "shell commands",
    help: "Strict: only test commands and the read commands an admin allowed run in the shell.",
    options: [{ value: "free", label: "Free" }, { value: "strict", label: "Strict" }],
  },
  {
    key: "path_rules", label: "Edits outside a phase's paths", words: "edits outside a phase's paths",
    help: "Strict: an edit outside the paths the phase names is refused instead of logged.",
    options: [{ value: "log", label: "Allow and log" }, { value: "strict", label: "Refuse" }],
  },
  {
    key: "device_models", label: "Model not in the list", words: "models outside the list",
    help: "List only: a device turn asking for a model outside the Workspace's list is refused instead of using the nearest listed model.",
    options: [{ value: "nearest", label: "Nearest listed model" }, { value: "list_only", label: "List only" }],
  },
  {
    key: "network", label: "Sandbox network", words: "sandbox network",
    help: "Allowlist: the sandbox reaches only the domains under Claude Code sandbox network on this page.",
    options: [{ value: "open", label: "Open" }, { value: "allowlist", label: "Allowlist only" }],
  },
  {
    key: "browser", label: "Browser pages", words: "browser pages",
    help: "Local only: a run's browser opens only localhost of your own app, no external pages.",
    options: [{ value: "read_external", label: "External pages too" }, { value: "loopback", label: "Local only" }],
  },
];

export const HARD_RULES_LINE = "Not settings, always enforced: reading credentials, uploads, deleting outside the job's "
  + "folder, destructive command patterns and pushes by the platform.";

const ROW_OF = new Map(TOOL_DEFAULT_ROWS.map((row) => [row.key, row]));
export const toolDefaultRow = (key: string): ToolDefaultRow | undefined => ROW_OF.get(key as ToolDefaultKey);
export const defaultValue = (key: ToolDefaultKey) => ROW_OF.get(key)!.options[0].value;
const isChoice = (key: ToolDefaultKey, value: unknown): value is string =>
  typeof value === "string" && ROW_OF.get(key)!.options.some((option) => option.value === value);

export function optionLabel(key: string, value: unknown): string {
  const option = toolDefaultRow(key)?.options.find((item) => item.value === value);
  return option ? option.label : String(value ?? "").replace(/_/g, " ");
}

export type ToolDefaultsView = { effective: ToolDefaults; canEdit: boolean; policyValid: boolean };

export function readToolDefaults(raw: unknown): ToolDefaultsView | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  const source = item.tool_defaults_effective;
  if (!source || typeof source !== "object") return null;
  const record = source as Record<string, unknown>;
  const effective = {} as ToolDefaults;
  for (const key of TOOL_DEFAULT_KEYS) effective[key] = isChoice(key, record[key]) ? record[key] : defaultValue(key);
  effective.allowed_tools = Array.isArray(record.allowed_tools)
    ? record.allowed_tools.filter((tool): tool is string => typeof tool === "string") : [];
  return { effective, canEdit: item.can_edit === true, policyValid: item.policy_valid !== false };
}

export const isChanged = (effective: ToolDefaults, key: ToolDefaultKey) => effective[key] !== defaultValue(key);

export const changedCount = (effective: ToolDefaults) => TOOL_DEFAULT_KEYS.filter((key) => isChanged(effective, key)).length;

/** The allowed-tools editor shows only while unknown tools are denied. */
export const showsAllowedTools = (effective: ToolDefaults) => effective.unknown_tools === "deny";

/** The server merges key by key, so only changed keys are sent; a key back at its default is sent as null. */
export function toolDefaultsPatch(change: Partial<ToolDefaults>) {
  const body: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(change)) {
    if (key === "allowed_tools") body.allowed_tools = Array.isArray(value) && value.length ? [...value] : null;
    else if (TOOL_DEFAULT_KEYS.includes(key as ToolDefaultKey)) {
      body[key] = value === defaultValue(key as ToolDefaultKey) ? null : value;
    }
  }
  return { tool_defaults: body };
}

export function allowedToolProblem(draft: string, current: readonly string[]): string | null {
  const value = draft.trim();
  if (!value) return "Enter a tool name, for example web.run or mcp__github__create_issue.";
  if (value.length > MAX_TOOL_NAME_CHARS) return `A tool name has at most ${MAX_TOOL_NAME_CHARS} characters.`;
  if (current.includes(value)) return "This tool is already listed.";
  if (current.length >= MAX_ALLOWED_TOOLS) return `At most ${MAX_ALLOWED_TOOLS} tools; remove one first.`;
  return null;
}

const REASONS: Record<string, string> = {
  invalid_tool_defaults: "The server did not accept these tool defaults; reload the page and try again.",
  invalid_tool_default: "The server does not know this value; reload the page and try again.",
  invalid_allowed_tools: `Each tool name has 1 to ${MAX_TOOL_NAME_CHARS} characters; at most ${MAX_ALLOWED_TOOLS} tools.`,
  agent_gateway_policy_invalid: "The Workspace's coding-tool policy has an invalid value; fix it on this page first.",
  workspace_admin_required: "Only the Workspace's admins and owners change this.",
  workspace_not_found: "This Workspace no longer exists or you are no longer a member.",
};

export function toolDefaultsErrorField(error: unknown): ToolDefaultKey | "allowed_tools" | "section" {
  const { code, path } = (error ?? {}) as { code?: string | null; path?: string | null };
  if (code === "invalid_allowed_tools") return "allowed_tools";
  const key = typeof path === "string" ? path.split(".").pop() : "";
  return code === "invalid_tool_default" && TOOL_DEFAULT_KEYS.includes(key as ToolDefaultKey)
    ? key as ToolDefaultKey : "section";
}

export function toolDefaultsErrorText(error: unknown): string {
  const { status, code } = (error ?? {}) as { status?: number; code?: string | null };
  if (code && REASONS[code]) return REASONS[code];
  if (status === 403) return REASONS.workspace_admin_required;
  if (status === 404) return REASONS.workspace_not_found;
  return "The change could not be saved. Try again.";
}
