import { useEffect, useRef, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { DataTable } from "../../../layout/DataTable";
import { PanelFooterSlotContext } from "../../../layout/PanelFooterSlot";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { openPolicies } from "../policyEngine/policyLinks";
import { usePolicyReferences } from "../policyEngine/usePolicyReferences";
import { ActionMenu } from "../workflowSurfaces/ActionMenu";
import { ConfiguredConnectorCard } from "./ConfiguredConnectorCard";
import { useConnectorLifecycle } from "./ConnectorDangerZone";
import { configuredConnectorStatus } from "./configuredConnectorStatus";
import { connectorToFocus } from "./connectorFocus";
import "./configuredConnectorStatus.css";
import "../adminDetailFacts.css";

type ConfiguredConnectorsSectionProps = {
  ctx: Record<string, unknown>;
};

// Connector settings: the built-in connectors as one compact table like Connections; a row opens
// its setup, named connections, checks and tools in the shared side panel, with Pause/Resume as the footer action and
// Remove… in the ⋯ menu.
export function ConfiguredConnectorsSection({
  ctx,
}: ConfiguredConnectorsSectionProps) {
  const { visibleConnectors, expandedConnector, handleExpandConnector, CONNECTOR_COLORS, CONNECTOR_ICONS, formatRelativeTime } = ctx as Record<string, any>;
  const { openAdminTab } = useAdminNavigation();
  const references = usePolicyReferences();
  const open = visibleConnectors.find((connector: any) => connector.tool_name === expandedConnector);
  // A Problems link (?connector=<name>) opens that connector once, when it is among the visible ones.
  const focused = useRef(false);
  useEffect(() => {
    if (focused.current) return;
    const target = connectorToFocus(visibleConnectors ?? [], typeof window === "undefined" ? "" : window.location.search);
    if (!target) return;
    focused.current = true;
    if (expandedConnector !== target.tool_name) handleExpandConnector(target.tool_name, target);
  }, [visibleConnectors, expandedConnector, handleExpandConnector]);

  const policies = (connector: any): number => references?.connectors[connector.tool_name]?.count ?? 0;
  const anyPolicies = visibleConnectors.some((connector: any) => policies(connector) > 0);
  const checked = (connector: any): string => {
    const health = connector.health ?? null;
    if (health?.last_checked && formatRelativeTime) return formatRelativeTime(health.last_checked);
    if (connector.configured) return "Not checked yet";
    return connector.workspace_connections ? "No global connection" : "Not configured";
  };

  return (
    <>
      <DataTable<any>
        label="Connectors"
        testId="connector-settings-table"
        rows={visibleConnectors}
        rowKey={(connector) => connector.tool_name}
        selectedKey={expandedConnector ?? null}
        onOpen={(connector) => { if (expandedConnector !== connector.tool_name) handleExpandConnector(connector.tool_name, connector); }}
        empty={{ text: "No connectors yet." }}
        columns={[
          { key: "name", header: "Name", grow: true, minWidth: "12rem", render: (connector) => (
            <span className="admin-detail-name">
              <span className="connector-card__icon connector-card__icon--small" style={{ background: CONNECTOR_COLORS?.[connector.tool_name] || "#666" }}>
                {CONNECTOR_ICONS?.[connector.tool_name] ?? <span className="connector-card__icon-fallback">{String(connector.label || "?")[0]}</span>}
              </span>
              <span>{connector.label}</span>
            </span>
          ) },
          { key: "tools", header: "Tools", nowrap: true, align: "end", render: (connector) => String(connector.tools?.length ?? 0) },
          { key: "state", header: "State", nowrap: true, clip: "20rem", render: (connector) => {
            const status = configuredConnectorStatus(connector, connector.health ?? null);
            return <StatusLabel label={status.text} tone={status.tone === "error" ? "problem" : "neutral"} title={status.text}
              testId={`connector-state-${connector.tool_name}`} />;
          } },
          { key: "checked", header: "Last checked", nowrap: true, render: checked },
          ...(anyPolicies ? [{ key: "policies", header: "Policies", nowrap: true, align: "end" as const, render: (connector: any) => {
            const count = policies(connector);
            return count ? (
              <button type="button" className="ds-link-button" title="Open the platform policies that name this connector"
                onClick={(event) => { event.stopPropagation(); openPolicies(openAdminTab, { connector: connector.tool_name }); }}>
                {count}
              </button>
            ) : "—";
          } }] : []),
        ]}
      />
      {open ? <ConnectorPanel key={open.tool_name} connector={open} ctx={ctx}
        onClose={() => handleExpandConnector(open.tool_name, open)} /> : null}
    </>
  );
}

// The setup's Test and Save sit in the panel footer, bottom right (PanelFooterSlot), with
// Pause/Resume at its left; the content is labelled form sections, the checks and named connections compact lists.
function ConnectorPanel({ connector, ctx, onClose }: { connector: any; ctx: Record<string, unknown>; onClose: () => void }) {
  const { toggle, menuItems, dialog } = useConnectorLifecycle(connector, ctx);
  const [footerSlot, setFooterSlot] = useState<HTMLElement | null>(null);
  return (
    <SidePanel
      title={connector.label}
      subtitle={connector.configured ? "Connector" : "Connector · not configured"}
      onClose={onClose}
      testId="connector-panel"
      headerActions={menuItems.length ? <ActionMenu row={{ objectName: connector.label }} items={menuItems} /> : null}
      footer={<>
        {toggle ? <span className="connector-panel__lifecycle">{toggle}</span> : null}
        <div ref={setFooterSlot} className="ds-panel__footer-slot" data-testid="connector-panel-footer" />
      </>}
    >
      <PanelFooterSlotContext.Provider value={footerSlot}>
        <ConfiguredConnectorCard connector={connector} ctx={ctx} inDrawer />
      </PanelFooterSlotContext.Provider>
      {dialog}
    </SidePanel>
  );
}
