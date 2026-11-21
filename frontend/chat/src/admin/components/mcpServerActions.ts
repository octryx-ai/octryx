// MCP server actions of the MCP page: connect, disconnect and remove one server of the active Workspace.
import type { Dispatch, SetStateAction } from "react";
import type { AdminMcpTabProps } from "./mcpTypes";
import { mcpServerActionPath } from "./mcpWorkspaceContract";

type McpServerActionsArgs = Pick<AdminMcpTabProps, "readJson" | "mcpWorkspaceId" | "loadMcpTab"> & {
  workspaceName: string;
  setOpenName: Dispatch<SetStateAction<string | null>>;
};

export function createMcpServerActions({
  readJson,
  mcpWorkspaceId,
  workspaceName,
  loadMcpTab,
  setOpenName,
}: McpServerActionsArgs) {
  const connectServer = async (serverName: string) => {
    try {
      await readJson(
        mcpServerActionPath(serverName, mcpWorkspaceId, "connect"),
        {
          method: "POST",
        },
      );
      loadMcpTab();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Connect failed");
    }
  };

  const disconnectServer = async (serverName: string) => {
    try {
      await readJson(
        mcpServerActionPath(serverName, mcpWorkspaceId, "disconnect"),
        {
          method: "POST",
        },
      );
      loadMcpTab();
    } catch (error) {
      window.alert(
        error instanceof Error ? error.message : "Disconnect failed",
      );
    }
  };

  const removeServer = async (serverName: string) => {
    if (
      !window.confirm(
        `Remove MCP server "${serverName}" (Workspace ${workspaceName})?`,
      )
    ) {
      return;
    }
    try {
      await readJson(mcpServerActionPath(serverName, mcpWorkspaceId), {
        method: "DELETE",
      });
      setOpenName((current) => (current === serverName ? null : current));
      loadMcpTab();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Delete failed");
    }
  };

  return { connectServer, disconnectServer, removeServer };
}
