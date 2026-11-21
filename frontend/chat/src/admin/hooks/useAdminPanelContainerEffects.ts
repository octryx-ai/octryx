import { useEffect } from "react";

export function useAdminPanelContainerEffects(params: {
  tab: string;
  mcpWorkspaceId: string;
  loadTab: (tab: string) => Promise<void>;
}) {
  const {
    tab,
    mcpWorkspaceId,
    loadTab,
  } = params;

  useEffect(() => {
    void loadTab(tab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  // Tab entry is loaded by the effect above; this one reloads the MCP tab when
  // its explicit Workspace selection changes.
  useEffect(() => {
    if (tab !== "mcp" || !mcpWorkspaceId) return;
    void loadTab("mcp");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mcpWorkspaceId]);
}
