import type { Dispatch, SetStateAction } from "react";
import type { MCPCatalogEntry, MCPServer } from "../components/mcpTypes";
import {
  mcpCatalogListPath,
  mcpServersListPath,
  mcpWorkspaceOptions,
  resolveMcpWorkspaceId,
} from "../components/mcpWorkspaceContract";
import type { AdminProjectQuality } from "../types/projectQualityTypes";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type LoadMcpTabDataArgs = {
  readJson: ReadJsonFn;
  adminProjects: AdminProjectQuality[];
  setAdminProjects: Dispatch<SetStateAction<AdminProjectQuality[]>>;
  mcpWorkspaceId: string;
  setMcpWorkspaceId: Dispatch<SetStateAction<string>>;
  setMcpServers: Dispatch<SetStateAction<MCPServer[]>>;
  setMcpCatalog: Dispatch<SetStateAction<MCPCatalogEntry[]>>;
};

/**
 * Load the MCP tab for one explicitly selected Workspace.
 *
 * The selection is resolved first (keep the current one while it is still an
 * active project, else the first active project). When that changes the
 * selection, the loader only stores it: the selection effect in
 * useAdminPanelContainerEffects reloads the tab with the new Workspace, so the
 * registry is never read for a Workspace the selector does not show.
 */
export async function loadMcpTabData({
  readJson,
  adminProjects,
  setAdminProjects,
  mcpWorkspaceId,
  setMcpWorkspaceId,
  setMcpServers,
  setMcpCatalog,
}: LoadMcpTabDataArgs) {
  let projects = adminProjects;
  if (projects.length === 0) {
    projects = await readJson<AdminProjectQuality[]>(
      "/admin/chat/api/panel/projects",
    );
    setAdminProjects(projects);
  }
  const workspaceId = resolveMcpWorkspaceId(
    mcpWorkspaceOptions(projects),
    mcpWorkspaceId,
  );
  if (!workspaceId) {
    setMcpWorkspaceId("");
    setMcpServers([]);
    setMcpCatalog([]);
    return;
  }
  if (workspaceId !== mcpWorkspaceId) {
    setMcpWorkspaceId(workspaceId);
    return;
  }
  const [serverData, catalogData] = await Promise.all([
    readJson<MCPServer[]>(mcpServersListPath(workspaceId)),
    readJson<MCPCatalogEntry[]>(mcpCatalogListPath(workspaceId)),
  ]);
  setMcpServers(serverData);
  setMcpCatalog(catalogData);
}
