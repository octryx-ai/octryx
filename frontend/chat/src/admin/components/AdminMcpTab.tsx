import { useEffect, useState } from "react";
import { AdminHeaderActions } from "./AdminHeaderSlot";
import { useActiveWorkspace } from "../../chat/useActiveWorkspace";
import { AdminMcpServerList } from "./AdminMcpServerList";
import { AdminMcpServerPanel } from "./AdminMcpServerPanel";
import { AdminMcpTabModals } from "./AdminMcpTabModals";
import {
  AdminMcpWorkspaceNotice,
} from "./AdminMcpWorkspaceSelect";
import { ActionMenu } from "./workflowSurfaces/ActionMenu";
import { McpAllowDrawer } from "./mcpAllow/McpAllowDrawer";
import { useMcpAllowStatus } from "./mcpAllow/useMcpAllowStatus";
import { createMcpServerActions } from "./mcpServerActions";
import type { AdminMcpTabProps, MCPServer } from "./mcpTypes";
import { mcpWorkspaceOptions } from "./mcpWorkspaceContract";

type AdminMcpTabWrapperProps = {
  ctx: Record<string, unknown>;
};

type WorkspaceOptions = ReturnType<typeof mcpWorkspaceOptions>;

// The tab follows the shared active workspace (never the first project). A
// change clears the previous Workspace's rows so no action targets them while
// the selection effect in useAdminPanelContainerEffects reloads the tab.
function useFollowActiveWorkspace(workspaceOptions: WorkspaceOptions, ctx: AdminMcpTabProps) {
  const { mcpWorkspaceId, setMcpCatalog, setMcpServers, setMcpWorkspaceId } = ctx;
  const [activeWorkspaceId] =
    useActiveWorkspace(workspaceOptions);
  useEffect(() => {
    if (activeWorkspaceId === mcpWorkspaceId) return;
    setMcpServers([]);
    setMcpCatalog([]);
    setMcpWorkspaceId(activeWorkspaceId);
  }, [
    activeWorkspaceId,
    mcpWorkspaceId,
    setMcpCatalog,
    setMcpServers,
    setMcpWorkspaceId,
  ]);
  return activeWorkspaceId;
}

// The open server's side panel, "Allow in Workspaces" and the row actions.
function useMcpServerPanel(ctx: AdminMcpTabProps, workspaceName: string) {
  const { mcpServers, openMcpServerEdit, readJson, mcpWorkspaceId, loadMcpTab } = ctx;
  // Registered → connected → allowed → tools visible, and "Allow in Workspaces".
  const allow = useMcpAllowStatus(mcpServers);
  const [allowing, setAllowing] = useState<{ id: string; name: string } | null>(null);
  // The server whose side panel is open (by name, the registry key). It closes on its own when the server is gone.
  const [openName, setOpenName] = useState<string | null>(null);
  const openServer = mcpServers.find((server) => server.name === openName) ?? null;

  const actions = createMcpServerActions({
    readJson,
    mcpWorkspaceId,
    workspaceName,
    loadMcpTab,
    setOpenName,
  });

  // Editing opens its own side panel; the server's panel steps aside (a custom server only gets the notice).
  const editServer = (server: MCPServer) => {
    if (server.catalog_slug) setOpenName(null);
    openMcpServerEdit(server);
  };

  const allowServer = (server: MCPServer) =>
    setAllowing(server.id ? { id: server.id, name: server.name } : null);

  return { allow, allowing, setAllowing, openName, setOpenName, openServer, ...actions, editServer, allowServer };
}

type ServerPanel = ReturnType<typeof useMcpServerPanel>;

// The "⋯" menu of a row and of the side panel; Remove (danger, confirmed) comes last.
function mcpServerMenu(panel: ServerPanel, server: MCPServer, inPanel = false) {
  const { editServer, disconnectServer, connectServer, allowServer, removeServer } = panel;
  return (
    <ActionMenu
      row={{ objectName: server.name }}
      items={[
        ...(inPanel
          ? []
          : [
              { label: "Edit", onSelect: () => editServer(server) },
              server.connected
                ? { label: "Disconnect", onSelect: () => void disconnectServer(server.name) }
                : { label: "Connect", onSelect: () => void connectServer(server.name) },
              ...(server.id ? [{ label: "Allow in Workspaces", onSelect: () => allowServer(server) }] : []),
            ]),
        ...(server.source_url
          ? [{
              label: "Open source",
              onSelect: () => window.open(server.source_url ?? "", "_blank", "noopener,noreferrer"),
            }]
          : []),
        { label: "Remove…", danger: true, onSelect: () => void removeServer(server.name) },
      ]}
    />
  );
}

// Both create flows (each opens a side panel); the catalog is the primary way. The Workspace is the global
// switch's (no own selector on this page).
function McpHeaderButtons({ hasWorkspace, onCustom, onCatalog }: { hasWorkspace: boolean; onCustom: () => void; onCatalog: () => void }) {
  return (
      <AdminHeaderActions>
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onCustom}
          disabled={!hasWorkspace}
          data-testid="mcp-add-custom"
        >
          Add custom MCP
        </button>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={onCatalog}
          disabled={!hasWorkspace}
          data-testid="mcp-install"
        >
          Install from catalog
        </button>
      </AdminHeaderActions>
  );
}

// The open server's side panel and, on top of it, "Allow in Workspaces".
function McpServerSurfaces({ panel, workspaceId }: { panel: ServerPanel; workspaceId: string }) {
  const { openServer, allowing, allow, setOpenName, setAllowing } = panel;
  return (
    <>
      {/* While "Allow in Workspaces" is open the server's panel steps aside, so Escape closes the drawer on top. */}
      {openServer && !allowing ? (
        <AdminMcpServerPanel
          server={openServer}
          workspaceId={workspaceId || undefined}
          status={openServer.id ? allow.status?.get(openServer.id) : undefined}
          onClose={() => setOpenName(null)}
          onEdit={panel.editServer}
          onConnect={(name) => void panel.connectServer(name)}
          onDisconnect={(name) => void panel.disconnectServer(name)}
          onAllow={panel.allowServer}
          menu={mcpServerMenu(panel, openServer, true)}
        />
      ) : null}
      {allowing ? (
        <McpAllowDrawer serverId={allowing.id} serverName={allowing.name} onClose={() => setAllowing(null)}
          onSaved={() => { setAllowing(null); allow.reload(); }} />
      ) : null}
    </>
  );
}

export function AdminMcpTab({ ctx: rawCtx }: AdminMcpTabWrapperProps) {
  const ctx = rawCtx as AdminMcpTabProps;
  const { adminProjects, mcpWorkspaceId, mcpServers, setShowMcpCatalog, setMcpCatalogSearch, openMcpCatalogInstall } = ctx;

  const workspaceOptions = mcpWorkspaceOptions(adminProjects);
  const workspaceName =
    workspaceOptions.find((option) => option.id === mcpWorkspaceId)?.name ??
    mcpWorkspaceId;
  const hasWorkspace = Boolean(mcpWorkspaceId);
  const activeWorkspaceId = useFollowActiveWorkspace(workspaceOptions, ctx);
  const panel = useMcpServerPanel(ctx, workspaceName);

  const openCatalog = () => {
    setMcpCatalogSearch("");
    setShowMcpCatalog(true);
  };
  const closeCatalog = () => setShowMcpCatalog(false);
  const handleSelectCatalogPreset = (
    preset: (typeof ctx.filteredMcpCatalog)[number],
  ) => {
    setShowMcpCatalog(false);
    setMcpCatalogSearch("");
    openMcpCatalogInstall(preset);
  };

  const showTable = workspaceOptions.length > 0 && Boolean(activeWorkspaceId);

  return (
    <div className="admin-mcp-page">
      <McpHeaderButtons hasWorkspace={hasWorkspace} onCustom={ctx.openCustomMcpForm} onCatalog={openCatalog} />

      <AdminMcpWorkspaceNotice options={workspaceOptions} value={activeWorkspaceId} />

      {showTable ? (
        <AdminMcpServerList
          servers={mcpServers}
          getMcpIconColor={ctx.getMcpIconColor}
          renderMcpIcon={ctx.renderMcpIcon}
          allowStatus={panel.allow.status}
          selectedName={panel.openName}
          onOpen={(server) => panel.setOpenName(server.name)}
          rowMenu={(server) => mcpServerMenu(panel, server)}
          empty={{
            text: "No MCP servers in this Workspace yet.",
            action: hasWorkspace ? { label: "Install from catalog", onClick: openCatalog } : undefined,
            testId: "mcp-empty",
          }}
        />
      ) : null}

      <McpServerSurfaces panel={panel} workspaceId={mcpWorkspaceId} />

      <AdminMcpTabModals ctx={ctx} workspaceName={workspaceName} closeCatalog={closeCatalog}
        onSelectPreset={handleSelectCatalogPreset} />
    </div>
  );
}
