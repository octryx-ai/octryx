// A run's `tool_allowed_by_default` and `tool_denied` events (allow by default; blocking is an admin
// option). Backend agent_gateway/tool_decision.py, at most MAX_DEFAULT_EVENTS of each per run:
// - `tool_allowed_by_default` `{tool, setting: "tool_defaults.<key>", session_id, path?}`: a quiet row "Allowed by
//   default: <tool> <path> (<setting in words>)", equal calls in a row folded into one, and a count for the summary;
// - `tool_denied` `{tool, reason, setting, remedy, message, session_id}`: a refusal row with the rule's message and,
//   when the refusal names one, its one-click fix. Pure: no React.

import { readRemedy, type Remedy } from "../devices/remedyModel";
import { toolDefaultRow } from "../devices/toolDefaultsModel";

export const ALLOWED_BY_DEFAULT_EVENT = "tool_allowed_by_default";
export const TOOL_DENIED_EVENT = "tool_denied";
export const MAX_DEFAULT_EVENTS = 200;

/** "web search and fetch" for `tool_defaults.web_tools`; an unknown key reads with spaces. */
export function settingWords(setting: unknown): string {
  const key = String(setting ?? "").replace(/^(device_runs\.)?tool_defaults\./, "");
  return toolDefaultRow(key)?.words ?? (key.replace(/_/g, " ") || "a Workspace default");
}

const toolOf = (detail: Record<string, unknown> | null | undefined) => String(detail?.tool ?? "").trim() || "a tool";
const pathOf = (detail: Record<string, unknown> | null | undefined) => String(detail?.path ?? "").trim();

export type AllowedByDefaultLine = { title: "Allowed by default"; text: string; quiet: true };

/** The row for one event or a run of equal ones (`times` > 1 adds "· 3 times"). */
export function allowedByDefaultLine(detail: Record<string, unknown> | null | undefined, times = 1): AllowedByDefaultLine {
  const path = pathOf(detail);
  const text = `${toolOf(detail)}${path ? ` ${path}` : ""} (${settingWords(detail?.setting)})${times > 1 ? ` · ${times} times` : ""}`;
  return { title: "Allowed by default", text, quiet: true };
}

/** Whether `next` continues the row `previous` started (same tool, path and setting). */
export function sameAllowedByDefault(previous: Record<string, unknown> | null | undefined,
  next: Record<string, unknown> | null | undefined): boolean {
  return toolOf(previous) === toolOf(next) && pathOf(previous) === pathOf(next)
    && String(previous?.setting ?? "") === String(next?.setting ?? "");
}

/** "12 tool calls allowed by default" for the run summary; "" for none. The backend stops recording at 200. */
export function allowedByDefaultCountText(events: { kind: string }[] | null | undefined): string {
  const count = (events ?? []).filter((event) => event.kind === ALLOWED_BY_DEFAULT_EVENT).length;
  if (!count) return "";
  if (count >= MAX_DEFAULT_EVENTS) return `${MAX_DEFAULT_EVENTS}+ tool calls allowed by default`;
  return `${count} tool call${count === 1 ? "" : "s"} allowed by default`;
}

export type ToolDeniedLine = { title: string; text: string; remedy?: Remedy };

/** The row for a refused tool call: "Refused: WebSearch" and the rule's message; its remedy when it names one. */
export function toolDeniedLine(detail: Record<string, unknown> | null | undefined): ToolDeniedLine {
  const message = String(detail?.message ?? "").replace(/\s+/g, " ").trim();
  const reason = String(detail?.reason ?? "").replace(/_/g, " ").trim();
  const remedy = readRemedy(detail?.remedy);
  return { title: `Refused: ${toolOf(detail)}`, text: message || reason || "blocked by the workspace rules",
    ...(remedy ? { remedy } : {}) };
}
