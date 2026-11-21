import type { ReactNode } from "react";

import { SidePanel } from "../../layout/SidePanel";
import { StatusLabel } from "../../layout/StatusLabel";
import { AdminDetailFacts } from "./AdminDetailFacts";
import type { ServerStatus } from "./mcpAllow/mcpAllowContract";
import { McpServerPipeline } from "./mcpAllow/McpServerPipeline";
import { McpToolRisks } from "./securityControls/McpToolRisks";
import { mcpScopeLabel, mcpServerState, mcpSourceLabel } from "./mcpServerPresenters";
import type { MCPServer } from "./mcpTypes";
import "./adminMcpCatalog.css";

type AdminMcpServerPanelProps = {
  server: MCPServer;
  // The Workspace whose tool bindings the risk selects edit; none: the section is left out.
  workspaceId?: string;
  // Registered → connected → allowed → tools visible, and "Allow in Workspaces".
  status?: ServerStatus;
  onClose: () => void;
  onEdit: (server: MCPServer) => void;
  onConnect: (serverName: string) => void;
  onDisconnect: (serverName: string) => void;
  onAllow?: (server: MCPServer) => void;
  // The "⋯" menu (Source, Remove), the same as the row's.
  menu: ReactNode;
};

// One MCP server in the side panel: its facts, the allow pipeline and, in the footer, Edit and Connect/Disconnect
// (last). Source and Remove are in the "⋯" menu of the header.
export function AdminMcpServerPanel({
  server,
  workspaceId,
  status,
  onClose,
  onEdit,
  onConnect,
  onDisconnect,
  onAllow,
  menu,
}: AdminMcpServerPanelProps) {
  const state = mcpServerState(server);
  // Empty facts (no endpoint, no vendor) are left out by AdminDetailFacts.
  const facts = [
    { label: "Endpoint", value: server.url },
    { label: "Transport", value: server.transport },
    { label: "Vendor", value: server.vendor },
    { label: "Preset", value: server.catalog_slug || "Custom configuration" },
    { label: "Scope", value: mcpScopeLabel(server) },
    { label: "Start", value: server.auto_start ? "Auto-start" : "Manual start" },
    { label: "Active", value: server.is_active === false ? "No" : "Yes" },
    { label: "Tools", value: server.connected ? `${server.tool_count} exposed` : "Not connected yet" },
  ];

  return (
    <SidePanel
      title={server.name}
      subtitle={`${mcpSourceLabel(server)} · ${mcpScopeLabel(server)} · ${server.transport}`}
      onClose={onClose}
      testId="mcp-server-panel"
      headerActions={(
        <>
          <StatusLabel label={state.label} tone={state.tone} testId="mcp-server-state" />
          {menu}
        </>
      )}
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={() => onEdit(server)}
            data-testid="mcp-server-edit">
            Edit
          </button>
          {server.connected ? (
            <button type="button" className="admin-panel__action-btn" onClick={() => onDisconnect(server.name)}
              data-testid="mcp-server-disconnect">
              Disconnect
            </button>
          ) : (
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
              onClick={() => onConnect(server.name)} data-testid="mcp-server-connect">
              Connect
            </button>
          )}
        </>
      )}
    >
      <div className="admin-mcp-panel">
        {server.description ? <p className="admin-mcp-panel__text">{server.description}</p> : null}
        <AdminDetailFacts facts={facts} testId="mcp-server-facts" />
        {server.id && onAllow ? (
          <McpServerPipeline status={status} onAllow={() => onAllow(server)} />
        ) : null}
        {workspaceId ? <McpToolRisks workspaceId={workspaceId} serverName={server.name} /> : null}
      </div>
    </SidePanel>
  );
}
