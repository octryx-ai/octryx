import type { ReactNode } from "react";

import { DataTable } from "../../layout/DataTable";
import type { EmptyLineProps } from "../../layout/EmptyLine";
import { StatusLabel } from "../../layout/StatusLabel";
import type { ServerStatus } from "./mcpAllow/mcpAllowContract";
import {
  mcpAllowedLabel,
  mcpScopeLabel,
  mcpServerState,
  mcpSourceLabel,
  mcpToolsText,
} from "./mcpServerPresenters";
import type { MCPServer } from "./mcpTypes";
import "./adminDetailFacts.css";

type AdminMcpServerListProps = {
  servers: MCPServer[];
  getMcpIconColor: (vendor?: string | null, name?: string) => string;
  renderMcpIcon: (vendor?: string | null, name?: string) => ReactNode;
  // How many Workspaces allow each server (by server id).
  allowStatus?: Map<string, ServerStatus>;
  selectedName: string | null;
  onOpen: (server: MCPServer) => void;
  rowMenu: (server: MCPServer) => ReactNode;
  empty: EmptyLineProps;
};

// The MCP servers of the selected Workspace (plus platform servers) as one full-width table; a row opens the
// server's side panel. What the columns mean is in the page help (help/admin/mcp.md).
export function AdminMcpServerList({
  servers,
  getMcpIconColor,
  renderMcpIcon,
  allowStatus,
  selectedName,
  onOpen,
  rowMenu,
  empty,
}: AdminMcpServerListProps) {
  return (
    <DataTable<MCPServer>
      label="MCP servers"
      testId="mcp-server-table"
      rows={servers}
      rowKey={(server) => server.name}
      selectedKey={selectedName}
      onOpen={onOpen}
      rowMenu={rowMenu}
      empty={empty}
      columns={[
        {
          key: "name",
          header: "Name",
          grow: true,
          render: (server) => (
            <span className="admin-detail-name">
              <span className="admin-detail-name__icon" aria-hidden="true"
                style={{ color: getMcpIconColor(server.vendor, server.name) }}>
                {renderMcpIcon(server.vendor, server.name)}
              </span>
              {server.name}
            </span>
          ),
        },
        { key: "source", header: "Source", nowrap: true, render: mcpSourceLabel },
        { key: "scope", header: "Scope", nowrap: true, render: mcpScopeLabel },
        { key: "transport", header: "Transport", nowrap: true, render: (server) => server.transport },
        {
          key: "state",
          header: "State",
          nowrap: true,
          render: (server) => {
            const state = mcpServerState(server);
            return <StatusLabel label={state.label} tone={state.tone} />;
          },
        },
        { key: "tools", header: "Tools", nowrap: true, align: "end", render: mcpToolsText },
        {
          key: "allowed",
          header: "Allowed in",
          nowrap: true,
          render: (server) => {
            const allowed = mcpAllowedLabel(server.id ? allowStatus?.get(server.id) : undefined);
            return allowed ? <StatusLabel label={allowed.label} tone={allowed.tone} /> : "—";
          },
        },
      ]}
    />
  );
}
