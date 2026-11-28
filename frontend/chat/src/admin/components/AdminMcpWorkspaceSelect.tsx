import { useAdminNavigation } from "../adminNavigation";
import { ChooseWorkspaceLine } from "../../chat/workspace/ChooseWorkspaceLine";
import type { McpWorkspaceOption } from "./mcpWorkspaceContract";
import { EmptyLine } from "../../layout/EmptyLine";

type AdminMcpWorkspaceNoticeProps = {
  options: McpWorkspaceOption[];
  value: string;
};

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
