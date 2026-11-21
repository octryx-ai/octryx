import { useMemo } from "react";

import { connectorCardShown } from "../components/connectorsTab/configuredConnectorStatus";
import type { AdminToolCatalogEntry, AdminConnector } from "../types/adminPanelTypes.usersProviders";
import type { AdminChannelRow as AdminChannel } from "../components/channelTypes";
import type { MCPCatalogEntry } from "../components/mcpTypes";

type UseAdminCatalogFiltersArgs = {
  connectors: AdminConnector[];
  expandedConnector: string | null;
  connectorCatalogSearch: string;
  availableChannels: AdminChannel[];
  channelCatalogSearch: string;
  mcpCatalog: MCPCatalogEntry[];
  mcpCatalogSearch: string;
  toolCatalog: AdminToolCatalogEntry[];
};

export function useAdminCatalogFilters({
  connectors,
  expandedConnector,
  connectorCatalogSearch,
  availableChannels,
  channelCatalogSearch,
  mcpCatalog,
  mcpCatalogSearch,
  toolCatalog,
}: UseAdminCatalogFiltersArgs) {
  const configuredConnectors = useMemo(
    () => connectors.filter((connector) => connector.configured),
    [connectors],
  );

  const availableConnectors = useMemo(
    () => connectors.filter((connector) => !connector.configured),
    [connectors],
  );

  const visibleConnectors = useMemo(
    () =>
      connectors.filter((connector) => connectorCardShown(connector, expandedConnector)),
    [connectors, expandedConnector],
  );

  const filteredAvailableConnectors = useMemo(() => {
    const query = connectorCatalogSearch.trim().toLowerCase();
    return availableConnectors.filter((connector) => {
      const haystack =
        `${connector.label} ${connector.description} ${connector.tool_name}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [availableConnectors, connectorCatalogSearch]);

  const filteredAvailableChannels = useMemo(() => {
    const query = channelCatalogSearch.trim().toLowerCase();
    return availableChannels.filter((channel) => {
      const haystack =
        `${channel.name} ${channel.description} ${channel.plugin_id}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [availableChannels, channelCatalogSearch]);

  const filteredMcpCatalog = useMemo(() => {
    const query = mcpCatalogSearch.trim().toLowerCase();
    return mcpCatalog.filter((preset) => {
      const haystack =
        `${preset.name} ${preset.vendor || ""} ${preset.description} ${preset.transport}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [mcpCatalog, mcpCatalogSearch]);

  const filteredToolCatalog = useMemo(() => {
    const query = connectorCatalogSearch.trim().toLowerCase();
    return toolCatalog.filter((tool) => {
      const haystack =
        `${tool.name} ${tool.description} ${tool.default_connector || ""} ${(tool.connectors || []).join(" ")}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [connectorCatalogSearch, toolCatalog]);

  return {
    availableConnectors,
    configuredConnectors,
    filteredAvailableChannels,
    filteredAvailableConnectors,
    filteredMcpCatalog,
    filteredToolCatalog,
    visibleConnectors,
  };
}
