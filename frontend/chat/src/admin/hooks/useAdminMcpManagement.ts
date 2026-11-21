import { type Dispatch, type SetStateAction } from "react";
import type { AdminTab } from "../types/adminPanelTypes.governance";
import type { MCPCatalogEntry, MCPServer } from "../components/mcpTypes";
import {
  MCP_DEFAULT_CUSTOM_TRANSPORT,
  MCP_SERVERS_CREATE_PATH,
  buildMcpCatalogInstallBody,
  buildMcpCatalogUpdateBody,
  buildMcpCustomServerBody,
  mcpCatalogInstallPath,
  mcpEditValuesFromSettings,
  mcpServerActionPath,
} from "../components/mcpWorkspaceContract";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type UseAdminMcpManagementArgs = {
  readJson: ReadJsonFn;
  loadTab: (tab: AdminTab) => Promise<void>;
  mcpWorkspaceId: string;
  selectedMcpCatalog: MCPCatalogEntry | null;
  setSelectedMcpCatalog: Dispatch<SetStateAction<MCPCatalogEntry | null>>;
  mcpCatalog: MCPCatalogEntry[];
  mcpEditingServerName: string | null;
  setMcpEditingServerName: Dispatch<SetStateAction<string | null>>;
  setMcpInstallName: Dispatch<SetStateAction<string>>;
  mcpInstallValues: Record<string, string>;
  setMcpInstallValues: Dispatch<SetStateAction<Record<string, string>>>;
  mcpInstallAutoStart: boolean;
  setMcpInstallAutoStart: Dispatch<SetStateAction<boolean>>;
  mcpInstallName: string;
  setMcpInstallError: Dispatch<SetStateAction<string | null>>;
  setMcpInstallLoading: Dispatch<SetStateAction<boolean>>;
  customMcpName: string;
  setCustomMcpName: Dispatch<SetStateAction<string>>;
  customMcpTransport: string;
  setCustomMcpTransport: Dispatch<SetStateAction<string>>;
  customMcpUrl: string;
  setCustomMcpUrl: Dispatch<SetStateAction<string>>;
  customMcpDescription: string;
  setCustomMcpDescription: Dispatch<SetStateAction<string>>;
  customMcpAutoStart: boolean;
  setCustomMcpAutoStart: Dispatch<SetStateAction<boolean>>;
  setShowAddCustomMcp: Dispatch<SetStateAction<boolean>>;
  setCustomMcpError: Dispatch<SetStateAction<string | null>>;
  setCustomMcpLoading: Dispatch<SetStateAction<boolean>>;
};

export function useAdminMcpManagement(args: UseAdminMcpManagementArgs) {
  const catalog = mcpCatalogActions(args);
  const custom = customMcpActions(args);
  return {
    closeCustomMcpForm: custom.closeCustomMcpForm,
    closeMcpCatalogInstall: catalog.closeMcpCatalogInstall,
    handleCreateCustomMcp: custom.handleCreateCustomMcp,
    handleInstallMcpCatalog: catalog.handleInstallMcpCatalog,
    openCustomMcpForm: custom.openCustomMcpForm,
    openMcpCatalogInstall: catalog.openMcpCatalogInstall,
    openMcpServerEdit: catalog.openMcpServerEdit,
  };
}

// Installing a catalog preset, or editing a server installed from one.
function mcpCatalogActions({
  readJson, loadTab, mcpWorkspaceId, selectedMcpCatalog, setSelectedMcpCatalog, mcpCatalog, mcpEditingServerName,
  setMcpEditingServerName, setMcpInstallName, mcpInstallValues, setMcpInstallValues, mcpInstallAutoStart,
  setMcpInstallAutoStart, mcpInstallName, setMcpInstallError, setMcpInstallLoading,
}: UseAdminMcpManagementArgs) {
  const openMcpCatalogInstall = (preset: MCPCatalogEntry) => {
    const initialValues: Record<string, string> = {};
    for (const field of preset.fields || []) {
      initialValues[field.name] = String(field.default || "");
    }
    setSelectedMcpCatalog(preset);
    setMcpEditingServerName(null);
    setMcpInstallName(preset.default_name || preset.slug);
    setMcpInstallValues(initialValues);
    setMcpInstallAutoStart(true);
    setMcpInstallError(null);
  };

  const closeMcpCatalogInstall = () => {
    setSelectedMcpCatalog(null);
    setMcpEditingServerName(null);
    setMcpInstallName("");
    setMcpInstallValues({});
    setMcpInstallAutoStart(true);
    setMcpInstallError(null);
  };

  const handleInstallMcpCatalog = async () => {
    if (!selectedMcpCatalog) return;
    setMcpInstallLoading(true);
    setMcpInstallError(null);
    try {
      await saveMcpCatalog(selectedMcpCatalog, { readJson, mcpWorkspaceId, mcpEditingServerName, mcpInstallName, mcpInstallAutoStart, mcpInstallValues });
      closeMcpCatalogInstall();
      void loadTab("mcp");
    } catch (error) {
      setMcpInstallError(error instanceof Error ? error.message : "Failed to install MCP preset");
    } finally {
      setMcpInstallLoading(false);
    }
  };

  const openMcpServerEdit = (server: MCPServer) => {
    const preset = mcpCatalog.find((entry) => entry.slug === server.catalog_slug);
    if (!preset) {
      window.alert("Custom MCP editing is not available yet.");
      return;
    }
    setSelectedMcpCatalog(preset);
    setMcpEditingServerName(server.name);
    setMcpInstallName(server.name);
    setMcpInstallValues(mcpEditValuesFromSettings(preset, server.settings));
    setMcpInstallAutoStart(server.auto_start);
    setMcpInstallError(null);
  };
  return { openMcpCatalogInstall, closeMcpCatalogInstall, handleInstallMcpCatalog, openMcpServerEdit };
}

// The custom server form: open, close, create.
function customMcpActions({
  readJson, loadTab, mcpWorkspaceId, customMcpName, setCustomMcpName, customMcpTransport, setCustomMcpTransport, customMcpUrl,
  setCustomMcpUrl, customMcpDescription, setCustomMcpDescription, customMcpAutoStart, setCustomMcpAutoStart,
  setShowAddCustomMcp, setCustomMcpError, setCustomMcpLoading,
}: UseAdminMcpManagementArgs) {
  const resetCustomMcpForm = () => {
    setCustomMcpName("");
    setCustomMcpTransport(MCP_DEFAULT_CUSTOM_TRANSPORT);
    setCustomMcpUrl("");
    setCustomMcpDescription("");
    setCustomMcpAutoStart(true);
    setCustomMcpError(null);
  };

  const openCustomMcpForm = () => {
    resetCustomMcpForm();
    setShowAddCustomMcp(true);
  };

  const closeCustomMcpForm = () => {
    setShowAddCustomMcp(false);
    resetCustomMcpForm();
  };

  const handleCreateCustomMcp = async () => {
    setCustomMcpLoading(true);
    setCustomMcpError(null);
    try {
      await readJson(MCP_SERVERS_CREATE_PATH, {
        method: "POST",
        body: JSON.stringify(buildMcpCustomServerBody({
          workspaceId: mcpWorkspaceId, name: customMcpName, transport: customMcpTransport, url: customMcpUrl,
          description: customMcpDescription, autoStart: customMcpAutoStart,
        })),
      });
      closeCustomMcpForm();
      void loadTab("mcp");
    } catch (error) {
      setCustomMcpError(error instanceof Error ? error.message : "Failed to create MCP server");
    } finally {
      setCustomMcpLoading(false);
    }
  };
  return { openCustomMcpForm, closeCustomMcpForm, handleCreateCustomMcp };
}

// An edited server is updated in place (PUT); a new preset is installed into the Workspace (POST).
function saveMcpCatalog(preset: MCPCatalogEntry, { readJson, mcpWorkspaceId, mcpEditingServerName, mcpInstallName, mcpInstallAutoStart, mcpInstallValues }:
  Pick<UseAdminMcpManagementArgs, "readJson" | "mcpWorkspaceId" | "mcpEditingServerName" | "mcpInstallName" | "mcpInstallAutoStart" | "mcpInstallValues">) {
  if (mcpEditingServerName) {
    return readJson(mcpServerActionPath(mcpEditingServerName, mcpWorkspaceId), {
      method: "PUT",
      body: JSON.stringify(buildMcpCatalogUpdateBody({ preset, autoStart: mcpInstallAutoStart, values: mcpInstallValues })),
    });
  }
  return readJson(mcpCatalogInstallPath(preset.slug), {
    method: "POST",
    body: JSON.stringify(buildMcpCatalogInstallBody({
      preset, workspaceId: mcpWorkspaceId, name: mcpInstallName, autoStart: mcpInstallAutoStart, values: mcpInstallValues,
    })),
  });
}
