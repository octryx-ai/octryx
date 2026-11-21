import { useState } from "react";
import type { AdminAgentMode } from "../types/adminPanelTypes.agents";
import type { AdminConnector, AdminDatabaseConnector, AdminDatabaseTool, AdminToolCatalogEntry } from "../types/adminPanelTypes.usersProviders";
import type { AdminScenarioProfile } from "../types/adminPanelTypes.governance";

export function useAdminConnectorCoreState() {
  const [connectors, setConnectors] = useState<AdminConnector[]>([]);
  const [databaseConnectors, setDatabaseConnectors] = useState<
    AdminDatabaseConnector[]
  >([]);
  const [databaseTools, setDatabaseTools] = useState<AdminDatabaseTool[]>([]);
  const [toolCatalog, setToolCatalog] = useState<AdminToolCatalogEntry[]>([]);
  const [scenarioProfiles, setScenarioProfiles] = useState<
    AdminScenarioProfile[]
  >([]);
  const [agentModes, setAgentModes] = useState<AdminAgentMode[]>([]);

  const [showAddConnector, setShowAddConnector] = useState(false);
  const [connectorCatalogSearch, setConnectorCatalogSearch] = useState("");
  const [expandedConnector, setExpandedConnector] = useState<string | null>(
    null,
  );
  const [connectorDraft, setConnectorDraft] = useState<
    Record<string, Record<string, string>>
  >({});
  const [connectorPolicyDraft, setConnectorPolicyDraft] = useState<
    Record<
      string,
      {
        tool_instructions: string;
        extra_tools: string[];
        disabled_tools: string[];
      }
    >
  >({});
  const [connectorToolSearch, setConnectorToolSearch] = useState<
    Record<string, string>
  >({});
  const [connectorSaving, setConnectorSaving] = useState<string | null>(null);
  const [connectorTesting, setConnectorTesting] = useState<string | null>(null);
  const [connectorTestResult, setConnectorTestResult] = useState<
    Record<string, { ok: boolean; summary: string; details?: string }>
  >({});

  return {
    agentModes,
    setAgentModes,
    connectorCatalogSearch,
    setConnectorCatalogSearch,
    connectorDraft,
    setConnectorDraft,
    connectors,
    setConnectors,
    connectorPolicyDraft,
    setConnectorPolicyDraft,
    connectorSaving,
    setConnectorSaving,
    connectorTesting,
    setConnectorTesting,
    connectorTestResult,
    setConnectorTestResult,
    connectorToolSearch,
    setConnectorToolSearch,
    databaseConnectors,
    setDatabaseConnectors,
    databaseTools,
    setDatabaseTools,
    expandedConnector,
    setExpandedConnector,
    scenarioProfiles,
    setScenarioProfiles,
    showAddConnector,
    setShowAddConnector,
    toolCatalog,
    setToolCatalog,
  };
}
