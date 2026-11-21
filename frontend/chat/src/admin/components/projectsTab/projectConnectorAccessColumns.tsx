// Columns of the Workspace connector access table: connector, Workspace state, limits and platform connector state.
import type { ReactNode } from "react";

import type { DataTableColumn } from "../../../layout/DataTable";
import { StatusLabel } from "../../../layout/StatusLabel";
import { connectionProduct } from "./workspaceConnectionModel";
import { connectorWorkspaceState, globalConnectorStatus, type AvailableConnection } from "./workspaceConnectorTableState";
import { savedProjectLimitCount, workspaceLimitText } from "./ProjectConnectorSettingsHelpers";
import type { ProjectConnectorAccess } from "./ProjectConnectorSettingsHelpers";

export function connectorAccessColumns(
  colors: Record<string, string>,
  icons: Record<string, ReactNode>,
  available: AvailableConnection[],
): DataTableColumn<ProjectConnectorAccess>[] {
  return [
    { key: "name", header: "Connector", grow: true, minWidth: "12rem", render: (connector) => (
      <span className="admin-detail-name">
        <span className="connector-card__icon connector-card__icon--small" style={{ background: colors[connector.connector_name] || "#6B7280" }}>
          {icons[connector.connector_name] ?? <span className="connector-card__icon-fallback">{connector.label[0]}</span>}
        </span>
        <span>{connector.label}</span>
      </span>
    ) },
    { key: "workspace", header: "In this Workspace", nowrap: true, render: (connector) => {
      const state = connectorWorkspaceState(connector, available).workspace;
      return <StatusLabel label={state.label} tone={state.tone} title={state.title}
        testId={`connector-workspace-state-${connector.connector_name}`} />;
    } },
    { key: "limits", header: "Limits", nowrap: true, render: (connector) => (
      <span data-testid="connector-limit-badge">{workspaceLimitText(savedProjectLimitCount(connector))}</span>
    ) },
    { key: "platform", header: "Platform connector", nowrap: true, render: (connector) => {
      const state = connectorWorkspaceState(connector, available).platform;
      return <StatusLabel label={state.label} tone={state.tone}
        title={state.title ?? `Platform connector: ${globalConnectorStatus(connector, Boolean(connectionProduct(connector.connector_name)))}`}
        testId={`connector-platform-state-${connector.connector_name}`} />;
    } },
  ];
}
