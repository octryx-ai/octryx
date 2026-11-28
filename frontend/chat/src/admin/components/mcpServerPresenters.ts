import type { StatusTone } from "../../layout/StatusLabel";
import type { ServerStatus } from "./mcpAllow/mcpAllowContract";
import type { MCPServer } from "./mcpTypes";

type ServerFacts = Pick<MCPServer, "connected" | "is_active" | "tool_count" | "catalog_slug" | "owner_scope">;

export function mcpServerState(server: ServerFacts): { label: string; tone: StatusTone } {
  if (server.is_active === false) return { label: "Inactive", tone: "neutral" };
  return { label: server.connected ? "Connected" : "Not connected", tone: "neutral" };
}

export const mcpSourceLabel = (server: ServerFacts) => (server.catalog_slug ? "Catalog" : "Custom");

export const mcpScopeLabel = (server: ServerFacts) => (server.owner_scope === "platform" ? "Platform" : "Workspace");

export const mcpToolsText = (server: ServerFacts) => (server.connected ? String(server.tool_count) : "—");

export function mcpAllowedLabel(status: ServerStatus | undefined): { label: string; tone: StatusTone } | null {
  if (!status) return null;
  const count = status.allowedWorkspaces;
  if (!count) return { label: "Not allowed", tone: "attention" };
  return { label: `${count} ${count === 1 ? "Workspace" : "Workspaces"}`, tone: "neutral" };
}
