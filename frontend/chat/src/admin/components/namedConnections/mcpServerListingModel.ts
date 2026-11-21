// MCP servers next to the named connections: the listing rows. MCP servers keep their own registry
// (several per scope, with transport, settings, secret bindings, readiness and a tool mirror) and are managed
// under Runtime → MCP servers; this model only turns the registry listing into display rows. A server URL is never
// shown (it may carry a token in its query), only the transport.

export type McpServerRow = {
  key: string;
  name: string;
  scope: string;
  transport: string;
  status: string;
};

type RawServer = {
  id?: unknown;
  name?: unknown;
  owner_scope?: unknown;
  workspace_id?: unknown;
  transport?: unknown;
  is_active?: unknown;
  connected?: unknown;
  tool_count?: unknown;
};

const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

export function mcpServerScopeLabel(server: RawServer, projectId: string): string {
  if (text(server.owner_scope) === "workspace") {
    return text(server.workspace_id) === projectId ? "This Workspace" : "Another Workspace";
  }
  return "Platform";
}

export function mcpServerStatus(server: RawServer): string {
  if (server.is_active === false) return "Inactive";
  if (server.connected !== true) return "Not connected";
  const tools = typeof server.tool_count === "number" && server.tool_count >= 0 ? server.tool_count : 0;
  return `Connected · ${tools} ${tools === 1 ? "tool" : "tools"}`;
}

/** The rows of a registry listing (`GET …/panel/mcp/servers?workspace_id=`); anything else is no rows. */
export function parseMcpServerRows(raw: unknown, projectId: string): McpServerRow[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((item): item is RawServer => Boolean(item) && typeof item === "object" && Boolean(text(item.name)))
    .map((server) => ({
      key: text(server.id) || text(server.name),
      name: text(server.name),
      scope: mcpServerScopeLabel(server, projectId),
      transport: text(server.transport) || "unknown",
      status: mcpServerStatus(server),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}
