import { readRemedy, type Remedy } from "../devices/remedyModel";
import { toolDefaultRow } from "../devices/toolDefaultsModel";

export const ALLOWED_BY_DEFAULT_EVENT = "tool_allowed_by_default";
export const TOOL_DENIED_EVENT = "tool_denied";
export const MAX_DEFAULT_EVENTS = 200;

export function settingWords(setting: unknown): string {
  const key = String(setting ?? "").replace(/^(device_runs\.)?tool_defaults\./, "");
  return toolDefaultRow(key)?.words ?? (key.replace(/_/g, " ") || "a Workspace default");
}

const toolOf = (detail: Record<string, unknown> | null | undefined) => String(detail?.tool ?? "").trim() || "a tool";
const pathOf = (detail: Record<string, unknown> | null | undefined) => String(detail?.path ?? "").trim();

export type AllowedByDefaultLine = { title: "Allowed by default"; text: string; quiet: true };

export function allowedByDefaultLine(detail: Record<string, unknown> | null | undefined, times = 1): AllowedByDefaultLine {
  const path = pathOf(detail);
  const text = `${toolOf(detail)}${path ? ` ${path}` : ""} (${settingWords(detail?.setting)})${times > 1 ? ` · ${times} times` : ""}`;
  return { title: "Allowed by default", text, quiet: true };
}

export function sameAllowedByDefault(previous: Record<string, unknown> | null | undefined,
  next: Record<string, unknown> | null | undefined): boolean {
  return toolOf(previous) === toolOf(next) && pathOf(previous) === pathOf(next)
    && String(previous?.setting ?? "") === String(next?.setting ?? "");
}

// The backend stops recording at 200 per run.
export function allowedByDefaultCountText(events: { kind: string }[] | null | undefined): string {
  const count = (events ?? []).filter((event) => event.kind === ALLOWED_BY_DEFAULT_EVENT).length;
  if (!count) return "";
  if (count >= MAX_DEFAULT_EVENTS) return `${MAX_DEFAULT_EVENTS}+ tool calls allowed by default`;
  return `${count} tool call${count === 1 ? "" : "s"} allowed by default`;
}

export type ToolDeniedLine = { title: string; text: string; remedy?: Remedy };

export function toolDeniedLine(detail: Record<string, unknown> | null | undefined): ToolDeniedLine {
  const message = String(detail?.message ?? "").replace(/\s+/g, " ").trim();
  const reason = String(detail?.reason ?? "").replace(/_/g, " ").trim();
  const remedy = readRemedy(detail?.remedy);
  return { title: `Refused: ${toolOf(detail)}`, text: message || reason || "blocked by the workspace rules",
    ...(remedy ? { remedy } : {}) };
}
