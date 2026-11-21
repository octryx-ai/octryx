// Pure presenter of the Tools page: source and availability labels, filters and search.
import type { AdminToolCatalogEntry } from "../../types/adminPanelTypes.usersProviders";

export type ToolSource = "base" | "connector" | "mcp" | "database";
export type ToolSourceFilter = "all" | "core" | "discoverable" | "connector" | "mcp" | "database";
export type ToolPolicyFilter = "all" | "core" | "discoverable" | "change_only" | "plan_excluded";

export const SOURCE_FILTER_OPTIONS: Array<{ id: ToolSourceFilter; label: string }> = [
  { id: "all", label: "All sources" },
  { id: "core", label: "Core tools" },
  { id: "discoverable", label: "Discoverable (searched on demand)" },
  { id: "connector", label: "From a connector" },
  { id: "mcp", label: "MCP" },
  { id: "database", label: "Database" },
];

export const POLICY_FILTER_OPTIONS: Array<{ id: ToolPolicyFilter; label: string }> = [
  { id: "all", label: "Any availability" },
  { id: "core", label: "Core only" },
  { id: "discoverable", label: "Discoverable only" },
  { id: "change_only", label: "Change modes only" },
  { id: "plan_excluded", label: "Not in plan mode" },
];

export function inferToolSource(tool: Pick<AdminToolCatalogEntry, "name">): ToolSource {
  if (tool.name.startsWith("connector_")) return "connector";
  if (tool.name.startsWith("mcp__")) return "mcp";
  if (tool.name.startsWith("database_tool_")) return "database";
  return "base";
}

function namedConnector(value: unknown): string {
  return typeof value === "string" && value.trim() && value !== "system" ? value.trim() : "";
}

// Where a tool comes from: its connector(s), otherwise "Built-in".
export function toolSourceLabel(tool: AdminToolCatalogEntry): string {
  if (inferToolSource(tool) === "connector") {
    const connectors = (Array.isArray(tool.connectors) ? tool.connectors : []).map(namedConnector).filter(Boolean);
    if (connectors.length) return connectors.join(", ");
  }
  return namedConnector(tool.default_connector) || "Built-in";
}

export function toolAvailability(tool: AdminToolCatalogEntry): { label: string; tone: "core" | "change" | "plan" | "discoverable" } {
  const labels = [tool.is_core ? "Core" : "Discoverable"];
  if (tool.change_only) labels.push("change modes only");
  if (tool.plan_excluded) labels.push("not in plan mode");
  if (tool.plan_only) labels.push("plan mode only");
  const tone = tool.is_core ? "core" : tool.change_only ? "change" : tool.plan_only || tool.plan_excluded ? "plan" : "discoverable";
  return { label: labels.join(" · "), tone };
}

export function filterTools(
  tools: AdminToolCatalogEntry[],
  source: ToolSourceFilter,
  policy: ToolPolicyFilter,
): AdminToolCatalogEntry[] {
  return tools
    .filter((tool) => {
      if (source === "core") return tool.is_core;
      if (source === "discoverable") return !tool.is_core;
      if (source === "connector" || source === "mcp" || source === "database") return inferToolSource(tool) === source;
      return true;
    })
    .filter((tool) => {
      if (policy === "core") return tool.is_core;
      if (policy === "discoverable") return !tool.is_core;
      if (policy === "change_only") return tool.change_only;
      if (policy === "plan_excluded") return tool.plan_excluded;
      return true;
    });
}
