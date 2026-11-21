// Admin › Connections › MCP servers: the words of the server table and its side panel. Pure: no React.
import type { StatusTone } from "../../layout/StatusLabel";
import type { ServerStatus } from "./mcpAllow/mcpAllowContract";
import type { MCPServer } from "./mcpTypes";

type ServerFacts = Pick<MCPServer, "connected" | "is_active" | "tool_count" | "catalog_slug" | "owner_scope">;

/** One state per server: an inactive registration first, then whether it is connected. */
export function mcpServerState(server: ServerFacts): { label: string; tone: StatusTone } {
  if (server.is_active === false) return { label: "Inactive", tone: "neutral" };
  return { label: server.connected ? "Connected" : "Not connected", tone: "neutral" };
}

export const mcpSourceLabel = (server: ServerFacts) => (server.catalog_slug ? "Catalog" : "Custom");

export const mcpScopeLabel = (server: ServerFacts) => (server.owner_scope === "platform" ? "Platform" : "Workspace");

/** The tool count is known only while the server is connected. */
export const mcpToolsText = (server: ServerFacts) => (server.connected ? String(server.tool_count) : "—");

/** "Allowed in": how many Workspaces may use the server; none needs an admin (attention). Null while unknown. */
export function mcpAllowedLabel(status: ServerStatus | undefined): { label: string; tone: StatusTone } | null {
  if (!status) return null;
  const count = status.allowedWorkspaces;
  if (!count) return { label: "Not allowed", tone: "attention" };
  return { label: `${count} ${count === 1 ? "Workspace" : "Workspaces"}`, tone: "neutral" };
}
