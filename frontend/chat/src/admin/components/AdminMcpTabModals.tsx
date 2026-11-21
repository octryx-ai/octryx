// The MCP page's create flows: the catalog picker, the catalog install (or edit) form and the custom server form.
import { AdminMcpCatalogModal } from "./AdminMcpCatalogModal";
import { AdminMcpCustomModal } from "./AdminMcpCustomModal";
import { AdminMcpInstallModal } from "./AdminMcpInstallModal";
import type { AdminMcpTabProps } from "./mcpTypes";

type Props = {
  ctx: AdminMcpTabProps;
  workspaceName: string;
  closeCatalog: () => void;
  onSelectPreset: (preset: AdminMcpTabProps["filteredMcpCatalog"][number]) => void;
};

export function AdminMcpTabModals({ ctx, workspaceName, closeCatalog, onSelectPreset }: Props) {
  return (
    <>
      <AdminMcpCatalogModal
        open={ctx.showMcpCatalog}
        close={closeCatalog}
        search={ctx.mcpCatalogSearch}
        setSearch={ctx.setMcpCatalogSearch}
        filteredCatalog={ctx.filteredMcpCatalog}
        onSelectPreset={onSelectPreset}
      />

      <AdminMcpInstallModal
        selectedPreset={ctx.selectedMcpCatalog}
        editingServerName={ctx.mcpEditingServerName}
        workspaceName={workspaceName}
        close={ctx.closeMcpCatalogInstall}
        mcpInstallName={ctx.mcpInstallName}
        setMcpInstallName={ctx.setMcpInstallName}
        mcpInstallValues={ctx.mcpInstallValues}
        setMcpInstallValues={ctx.setMcpInstallValues}
        mcpInstallAutoStart={ctx.mcpInstallAutoStart}
        setMcpInstallAutoStart={ctx.setMcpInstallAutoStart}
        mcpInstallError={ctx.mcpInstallError}
        mcpInstallLoading={ctx.mcpInstallLoading}
        handleInstallMcpCatalog={ctx.handleInstallMcpCatalog}
      />

      <AdminMcpCustomModal
        open={ctx.showAddCustomMcp}
        workspaceName={workspaceName}
        close={ctx.closeCustomMcpForm}
        customMcpName={ctx.customMcpName}
        setCustomMcpName={ctx.setCustomMcpName}
        customMcpTransport={ctx.customMcpTransport}
        setCustomMcpTransport={ctx.setCustomMcpTransport}
        customMcpUrl={ctx.customMcpUrl}
        setCustomMcpUrl={ctx.setCustomMcpUrl}
        customMcpDescription={ctx.customMcpDescription}
        setCustomMcpDescription={ctx.setCustomMcpDescription}
        customMcpAutoStart={ctx.customMcpAutoStart}
        setCustomMcpAutoStart={ctx.setCustomMcpAutoStart}
        customMcpLoading={ctx.customMcpLoading}
        customMcpError={ctx.customMcpError}
        onCreate={ctx.handleCreateCustomMcp}
      />
    </>
  );
}
