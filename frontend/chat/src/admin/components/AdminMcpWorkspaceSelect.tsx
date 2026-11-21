import { useAdminNavigation } from "../adminNavigation";
import { ChooseWorkspaceLine } from "../../chat/workspace/ChooseWorkspaceLine";
import type { McpWorkspaceOption } from "./mcpWorkspaceContract";
import { EmptyLine } from "../../layout/EmptyLine";

type AdminMcpWorkspaceNoticeProps = {
  options: McpWorkspaceOption[];
  value: string;
};

/**
 * MCP servers follow the global Workspace switch (the page had its own Workspace selector in the
 * header; the global switch is the only one). The one line the page shows instead of the table while there is no
 * Workspace, or none is chosen: the choice sets the global active Workspace. What the scope means is in the page help
 * (help/admin/mcp.md).
 */
export function AdminMcpWorkspaceNotice({ options, value }: AdminMcpWorkspaceNoticeProps) {
  const { openAdminTab } = useAdminNavigation();

  if (options.length === 0) {
    return (
      <EmptyLine
        text="No active Workspace yet."
        action={{ label: "Open Workspaces", onClick: () => openAdminTab("projects") }}
        testId="mcp-no-workspace"
      />
    );
  }
  if (!value) {
    return <ChooseWorkspaceLine projects={options} purpose="to see its MCP servers" testId="mcp-select-workspace" />;
  }
  return null;
}
