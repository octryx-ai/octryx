import { TOOL_DEFAULT_KEYS, optionLabel, toolDefaultRow, type ToolDefaultKey } from "./toolDefaultsModel";

export const REMEDY_PREFIX = "device_runs.tool_defaults.";
export const REMEDY_BUTTON = "Allow in this Workspace";

export type Remedy = { setting: string; key: ToolDefaultKey | "allowed_tools"; value: unknown; tool: string | null };

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;

export function readRemedy(raw: unknown): Remedy | null {
  if (!isRecord(raw) || typeof raw.setting !== "string" || !raw.setting.startsWith(REMEDY_PREFIX)) return null;
  const key = raw.setting.slice(REMEDY_PREFIX.length);
  const tool = typeof raw.tool === "string" && raw.tool.trim() ? raw.tool.trim() : null;
  if (key === "allowed_tools") return tool ? { setting: raw.setting, key, value: raw.value, tool } : null;
  if (!TOOL_DEFAULT_KEYS.includes(key as ToolDefaultKey) || typeof raw.value !== "string") return null;
  return { setting: raw.setting, key: key as ToolDefaultKey, value: raw.value, tool };
}

export function remedyOfResult(result: unknown): Remedy | null {
  if (typeof result === "string") {
    const text = result.trim();
    if (!text.startsWith("{")) return null;
    try {
      return remedyOfResult(JSON.parse(text));
    } catch {
      return null;
    }
  }
  return isRecord(result) ? readRemedy(result.remedy) : null;
}

export function remedyChangeText(remedy: Remedy): string {
  if (remedy.key === "allowed_tools") {
    return `Adds “${remedy.tool}” to the tools allowed in this Workspace while tools without a rule are denied.`;
  }
  const label = toolDefaultRow(remedy.key)?.label ?? remedy.key;
  return `Sets “${label}” to “${optionLabel(remedy.key, remedy.value)}” for this Workspace.`;
}

export function remedyBody(remedy: Remedy): Record<string, unknown> {
  return { setting: remedy.setting, value: remedy.value, ...(remedy.tool ? { tool: remedy.tool } : {}) };
}

export function remedyDoneText(remedy: Remedy): string {
  const what = remedy.key === "allowed_tools"
    ? `“${remedy.tool}” is allowed in this Workspace`
    : `“${toolDefaultRow(remedy.key)?.label ?? remedy.key}” is now “${optionLabel(remedy.key, remedy.value)}”`;
  return `${what}. It applies to the next tool call; ask the agent to try again.`;
}

const REMEDY_ERRORS: Record<string, string> = {
  workspace_admin_required: "Only the Workspace's admins and owners can allow this.",
  remedy_invalid: "The server does not know this setting any more; change it under Coding tools & devices › Tool defaults.",
  remedy_tool_missing: "The refusal did not name the tool; add it under Coding tools & devices › Tool defaults.",
  workspace_not_found: "This Workspace no longer exists or you are no longer a member.",
  invalid_allowed_tools: "The list of allowed tools is full or the tool name is too long; edit it under Tool defaults.",
  invalid_tool_defaults: "The server did not accept the change; reload the page and try again.",
  agent_gateway_policy_invalid: "The Workspace's coding-tool policy has an invalid value; fix it under Coding tools & devices first.",
};

export function remedyErrorText(error: unknown): string {
  const { status, code } = (error ?? {}) as { status?: number; code?: string | null };
  if (code && REMEDY_ERRORS[code]) return REMEDY_ERRORS[code];
  if (status === 403) return REMEDY_ERRORS.workspace_admin_required;
  if (status === 404) return REMEDY_ERRORS.workspace_not_found;
  return "The change could not be saved. Try again.";
}
