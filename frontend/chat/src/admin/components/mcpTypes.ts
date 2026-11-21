import type { Dispatch, ReactNode, SetStateAction } from "react";

export type MCPServer = {
  id?: string;
  name: string;
  owner_scope?: "platform" | "workspace" | string;
  workspace_id?: string | null;
  transport: string;
  url: string | null;
  description: string;
  auto_start: boolean;
  is_active?: boolean;
  settings?: Record<string, string>;
  connected: boolean;
  tool_count: number;
  catalog_slug?: string | null;
  vendor?: string | null;
  source_url?: string | null;
};

export type MCPCatalogField = {
  name: string;
  label: string;
  type: string;
  required?: boolean;
  default?: string;
  options?: string[];
  placeholder?: string;
};

export type MCPCatalogEntry = {
  slug: string;
  name: string;
  vendor?: string | null;
  description: string;
  source_url: string;
  transport: string;
  default_name: string;
  fields: MCPCatalogField[];
  installed_names: string[];
  installed_count: number;
};

/** The fields of an admin project row the Workspace selector needs. */
export type McpWorkspaceSourceRow = {
  id: string;
  name: string;
  is_active: boolean;
};

export type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

export type AdminMcpTabProps = {
  adminProjects: McpWorkspaceSourceRow[];
  mcpWorkspaceId: string;
  setMcpWorkspaceId: Dispatch<SetStateAction<string>>;
  mcpServers: MCPServer[];
  setMcpServers: Dispatch<SetStateAction<MCPServer[]>>;
  setMcpCatalog: Dispatch<SetStateAction<MCPCatalogEntry[]>>;
  mcpCatalog: MCPCatalogEntry[];
  filteredMcpCatalog: MCPCatalogEntry[];
  showMcpCatalog: boolean;
  setShowMcpCatalog: Dispatch<SetStateAction<boolean>>;
  mcpCatalogSearch: string;
  setMcpCatalogSearch: Dispatch<SetStateAction<string>>;
  openMcpCatalogInstall: (preset: MCPCatalogEntry) => void;
  selectedMcpCatalog: MCPCatalogEntry | null;
  closeMcpCatalogInstall: () => void;
  mcpEditingServerName: string | null;
  mcpInstallName: string;
  setMcpInstallName: Dispatch<SetStateAction<string>>;
  mcpInstallValues: Record<string, string>;
  setMcpInstallValues: Dispatch<SetStateAction<Record<string, string>>>;
  mcpInstallAutoStart: boolean;
  setMcpInstallAutoStart: Dispatch<SetStateAction<boolean>>;
  mcpInstallError: string | null;
  mcpInstallLoading: boolean;
  handleInstallMcpCatalog: () => Promise<void>;
  openMcpServerEdit: (server: MCPServer) => void;
  showAddCustomMcp: boolean;
  openCustomMcpForm: () => void;
  closeCustomMcpForm: () => void;
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
  customMcpLoading: boolean;
  customMcpError: string | null;
  handleCreateCustomMcp: () => Promise<void>;
  getMcpIconColor: (vendor?: string | null, name?: string) => string;
  renderMcpIcon: (vendor?: string | null, name?: string) => ReactNode;
  readJson: ReadJsonFn;
  loadMcpTab: () => void;
};
