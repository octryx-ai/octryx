export function parseToolList(value: string | null | undefined): string[] {
  const seen = new Set<string>();
  const ids: string[] = [];
  for (const raw of (value || "").split(",")) {
    const id = raw.trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
  }
  return ids;
}

export function serializeToolList(ids: string[]): string {
  return parseToolList(ids.join(",")).join(", ");
}

export function normalizeToolCatalog(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return parseToolList(raw.filter((item): item is string => typeof item === "string").join(","));
}

// does not. Unknown IDs stay selected: they are only removed explicitly.
export function splitByCatalog(selected: string[], catalog: string[]): { known: string[]; unknown: string[] } {
  const inCatalog = new Set(catalog);
  return {
    known: selected.filter((id) => inCatalog.has(id)),
    unknown: selected.filter((id) => !inCatalog.has(id)),
  };
}

export function toggleTool(value: string, id: string, checked: boolean): string {
  const ids = parseToolList(value);
  const tool = id.trim();
  if (!tool) return serializeToolList(ids);
  const without = ids.filter((item) => item !== tool);
  return serializeToolList(checked ? [...without, tool] : without);
}

export function removeTool(value: string, id: string): string {
  return toggleTool(value, id, false);
}

export function filterToolCatalog(catalog: string[], query: string): string[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return catalog;
  return catalog.filter((id) => id.toLowerCase().includes(needle));
}

export const STEP_CONFIG_JSON_ERROR = "Step configuration must be valid JSON.";

export function stepConfigIssue(config: string | null | undefined): string | null {
  try {
    JSON.parse(config || "{}");
    return null;
  } catch {
    return STEP_CONFIG_JSON_ERROR;
  }
}

type ConfigObject = Record<string, unknown>;

export const TOOL_USE_KEY = "tool_use";

function parseConfigObject(config: string | null | undefined): ConfigObject | null {
  try {
    const parsed = JSON.parse(config || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as ConfigObject) : null;
  } catch {
    return null;
  }
}

export function stepConfigNeedsAttention(config: string | null | undefined): boolean {
  if (!(config || "").trim()) return false;
  const parsed = parseConfigObject(config);
  if (!parsed) return true;
  return Object.keys(parsed).some((key) => key !== TOOL_USE_KEY);
}

// Mirrors agent/core/guards/step_tool_requirement.py; an unrecognised value fails closed to required.
export type ToolUse = "required" | "optional";
export type ToolUseState = {
  value: ToolUse;
  source: "explicit" | "default" | "unrecognized";
  writable: boolean;
};

export function toolUseState(config: string | null | undefined, allowedTools: string | null | undefined): ToolUseState {
  const parsed = parseConfigObject(config);
  const fromAllowedTools: ToolUse = parseToolList(allowedTools).length > 0 ? "required" : "optional";
  if (!parsed) return { value: fromAllowedTools, source: "default", writable: false };
  const raw = parsed[TOOL_USE_KEY];
  if (raw === undefined || raw === null) return { value: fromAllowedTools, source: "default", writable: true };
  const saved = typeof raw === "string" ? raw.trim().toLowerCase() : "";
  if (saved === "required" || saved === "optional") return { value: saved, source: "explicit", writable: true };
  return { value: "required", source: "unrecognized", writable: true };
}

export function toolUseDefaultNote(allowedTools: string | null | undefined): string {
  return parseToolList(allowedTools).length > 0
    ? "Current default: required because tools are listed."
    : "Current default: optional because no tools are listed.";
}

export function writeToolUse(config: string | null | undefined, value: ToolUse): string | null {
  const parsed = parseConfigObject(config);
  if (!parsed) return null;
  return JSON.stringify({ ...parsed, [TOOL_USE_KEY]: value }, null, 2);
}
