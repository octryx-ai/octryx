import { AddConnectorModal } from "./connectorsTab/AddConnectorModal";
import { ConfiguredConnectorsSection } from "./connectorsTab/ConfiguredConnectorsSection";
import { ConnectorOverviewSection } from "./connectorsTab/ConnectorOverviewSection";
import { PrivateHostAllowlistSection } from "./connectorsTab/PrivateHostAllowlistSection";
import "./automation/automationPages.css";

type AdminConnectorsTabProps = {
  ctx: Record<string, unknown>;
};

export function AdminConnectorsTab({ ctx }: AdminConnectorsTabProps) {
  const configured = (ctx.configuredConnectors || []) as Array<{ tool_name: string }>;
  // Overview, the connector grid, then the collapsed private hosts section.
  return (
    <div className="automation-page">
      <ConnectorOverviewSection ctx={ctx} />
      <ConfiguredConnectorsSection ctx={ctx} />
      <PrivateHostAllowlistSection
        configuredConnectors={configured.map((connector) => connector.tool_name)}
      />
      <AddConnectorModal ctx={ctx} />
    </div>
  );
}
