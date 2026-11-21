// The one-click fix a refused tool call names (allow by default; blocking is an admin option).
// Backend agent_gateway/tool_check.py `setting_remedy`: `{setting: "device_runs.tool_defaults.<key>", value, tool?}`,
// in the hook answer and in the denied ToolCall row's `result.remedy`; POST
// `/api/v1/workspaces/{id}/agent-gateway/device-runs/remedy` applies it (Workspace admins/owners; `allowed_tools` adds
// `tool`) and answers like GET device-runs. Pure: no React.

import { TOOL_DEFAULT_KEYS, optionLabel, toolDefaultRow, type ToolDefaultKey } from "./toolDefaultsModel";

export const REMEDY_PREFIX = "device_runs.tool_defaults.";
export const REMEDY_BUTTON = "Allow in this Workspace";

export type Remedy = { setting: string; key: ToolDefaultKey | "allowed_tools"; value: unknown; tool: string | null };

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;

/** A remedy object, or null for anything this UI cannot apply (unknown key, `allowed_tools` without a tool). */
export function readRemedy(raw: unknown): Remedy | null {
  if (!isRecord(raw) || typeof raw.setting !== "string" || !raw.setting.startsWith(REMEDY_PREFIX)) return null;
  const key = raw.setting.slice(REMEDY_PREFIX.length);
  const tool = typeof raw.tool === "string" && raw.tool.trim() ? raw.tool.trim() : null;
  if (key === "allowed_tools") return tool ? { setting: raw.setting, key, value: raw.value, tool } : null;
  if (!TOOL_DEFAULT_KEYS.includes(key as ToolDefaultKey) || typeof raw.value !== "string") return null;
  return { setting: raw.setting, key: key as ToolDefaultKey, value: raw.value, tool };
}

/** The remedy a refused tool call carries in its result (`result.remedy`, or the result as a JSON text). */
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

/** What the confirmation names: exactly which setting changes, to which value, or which tool is added. */
export function remedyChangeText(remedy: Remedy): string {
  if (remedy.key === "allowed_tools") {
    return `Adds “${remedy.tool}” to the tools allowed in this Workspace while tools without a rule are denied.`;
  }
  const label = toolDefaultRow(remedy.key)?.label ?? remedy.key;
  return `Sets “${label}” to “${optionLabel(remedy.key, remedy.value)}” for this Workspace.`;
}

/** The POST body: the remedy as the refusal gave it. */
export function remedyBody(remedy: Remedy): Record<string, unknown> {
  return { setting: remedy.setting, value: remedy.value, ...(remedy.tool ? { tool: remedy.tool } : {}) };
}

/** The line after the remedy was applied. */
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

/** A refused POST in words. */
export function remedyErrorText(error: unknown): string {
  const { status, code } = (error ?? {}) as { status?: number; code?: string | null };
  if (code && REMEDY_ERRORS[code]) return REMEDY_ERRORS[code];
  if (status === 403) return REMEDY_ERRORS.workspace_admin_required;
  if (status === 404) return REMEDY_ERRORS.workspace_not_found;
  return "The change could not be saved. Try again.";
}
