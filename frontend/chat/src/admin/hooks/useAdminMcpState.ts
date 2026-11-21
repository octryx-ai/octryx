import { useState } from "react";
import type { MCPCatalogEntry, MCPServer } from "../components/mcpTypes";
import { MCP_DEFAULT_CUSTOM_TRANSPORT } from "../components/mcpWorkspaceContract";

export function useAdminMcpState() {
  // The Workspace every MCP registry call is scoped to; resolved by the loader.
  const [mcpWorkspaceId, setMcpWorkspaceId] = useState("");
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [mcpCatalog, setMcpCatalog] = useState<MCPCatalogEntry[]>([]);
  const [showMcpCatalog, setShowMcpCatalog] = useState(false);
  const [mcpCatalogSearch, setMcpCatalogSearch] = useState("");
  const [selectedMcpCatalog, setSelectedMcpCatalog] =
    useState<MCPCatalogEntry | null>(null);
  const [mcpEditingServerName, setMcpEditingServerName] = useState<
    string | null
  >(null);
  const [mcpInstallName, setMcpInstallName] = useState("");
  const [mcpInstallValues, setMcpInstallValues] = useState<
    Record<string, string>
  >({});
  const [mcpInstallAutoStart, setMcpInstallAutoStart] = useState(true);
  const [mcpInstallLoading, setMcpInstallLoading] = useState(false);
  const [mcpInstallError, setMcpInstallError] = useState<string | null>(null);
  const [showAddCustomMcp, setShowAddCustomMcp] = useState(false);
  const [customMcpName, setCustomMcpName] = useState("");
  const [customMcpTransport, setCustomMcpTransport] = useState<string>(
    MCP_DEFAULT_CUSTOM_TRANSPORT,
  );
  const [customMcpUrl, setCustomMcpUrl] = useState("");
  const [customMcpDescription, setCustomMcpDescription] = useState("");
  const [customMcpAutoStart, setCustomMcpAutoStart] = useState(true);
  const [customMcpLoading, setCustomMcpLoading] = useState(false);
  const [customMcpError, setCustomMcpError] = useState<string | null>(null);

  return {
    customMcpAutoStart,
    setCustomMcpAutoStart,
    customMcpDescription,
    setCustomMcpDescription,
    customMcpError,
    setCustomMcpError,
    customMcpLoading,
    setCustomMcpLoading,
    customMcpName,
    setCustomMcpName,
    customMcpTransport,
    setCustomMcpTransport,
    customMcpUrl,
    setCustomMcpUrl,
    mcpCatalog,
    setMcpCatalog,
    mcpCatalogSearch,
    setMcpCatalogSearch,
    mcpInstallAutoStart,
    setMcpInstallAutoStart,
    mcpInstallError,
    setMcpInstallError,
    mcpInstallLoading,
    setMcpInstallLoading,
    mcpInstallName,
    setMcpInstallName,
    mcpInstallValues,
    setMcpInstallValues,
    mcpEditingServerName,
    setMcpEditingServerName,
    mcpServers,
    setMcpServers,
    mcpWorkspaceId,
    setMcpWorkspaceId,
    selectedMcpCatalog,
    setSelectedMcpCatalog,
    showAddCustomMcp,
    setShowAddCustomMcp,
    showMcpCatalog,
    setShowMcpCatalog,
  };
}
