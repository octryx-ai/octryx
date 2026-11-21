import { useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { readJson } from "../../utils/adminPanelHelpers";
import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { PanelFooterSlotContext } from "../../../layout/PanelFooterSlot";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { CatalogSwitch } from "../modelCatalog/CatalogSwitch";
import { ActionMenu, type ActionMenuItem } from "../workflowSurfaces/ActionMenu";
import "../modelCatalog/modelCatalog.css";
import { ProvidersLocalBootstrapCard } from "./ProvidersLocalBootstrapCard";
import { ProviderAuthSection } from "./ProviderAuthSection";
import { connectionView } from "./providerConnection";
import { LITELLM_GATEWAY_DRIVER } from "./litellmGatewayTypes";
import type { ProviderTabCtx } from "./types";

type ProvidersListProps = {
  ctx: ProviderTabCtx;
};

const PROVIDERS_PATH = "/admin/chat/api/panel/providers";

// The table columns: name, connection, state and the Enabled switch.
function providerColumns(onToggle: (provider: any, next: boolean) => void): DataTableColumn<any>[] {
  return [
    { key: "name", header: "Name", nowrap: true, render: (p) => <span data-testid={`provider-card-${p.id}`}>{p.display_name}</span> },
    { key: "details", header: "Connection", grow: true, render: (p) => connectionView(p).meta || "—" },
    { key: "state", header: "State", nowrap: true, render: (p) => {
      const view = connectionView(p);
      return <StatusLabel label={view.status} tone={view.tone === "attention" ? "attention" : "neutral"} />;
    } },
    { key: "enabled", header: "Enabled", nowrap: true, align: "end", render: (p) => (
      <CatalogSwitch on={Boolean(p.is_active)} label={`${p.display_name}: enabled`}
        testId={`provider-enabled-${p.id}`} onChange={(next) => onToggle(p, next)} />
    ) },
  ];
}

// Models › Providers: one full-width table row per connection with its kind, health and an Enabled
// switch; the row opens the connection fields in a side panel. "Models" (opens the Model catalog) and "Delete
// provider…" sit in the row's and the panel's ⋯ menu. Model choices live in the Model catalog.
export function ProvidersList({ ctx }: ProvidersListProps) {
  const {
    expandedProvider,
    handleDeleteProvider,
    handleToggleProvider,
    providers,
  } = ctx;
  const { openAdminTab } = useAdminNavigation();
  const [active, setActive] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");
  // The panel footer the gateway form puts its Reset / Save changes into.
  const [footerSlot, setFooterSlot] = useState<HTMLElement | null>(null);

  const toggleActive = async (provider: Record<string, any>, next: boolean) => {
    setError("");
    try {
      const updated = await readJson<Record<string, any>>(`${PROVIDERS_PATH}/${encodeURIComponent(provider.id)}`, {
        method: "PUT",
        body: JSON.stringify({ is_active: next }),
      });
      setActive((current) => ({ ...current, [provider.id]: updated?.is_active !== false && next }));
    } catch {
      setError(`${provider.display_name || "The provider"} could not be ${next ? "enabled" : "disabled"}.`);
    }
  };

  const rows = providers.map((raw: any) => ({ ...raw, is_active: active[raw.id] ?? raw.is_active }));
  const open = rows.find((p: any) => p.id === expandedProvider) ?? null;
  const menuItems = (p: any): ActionMenuItem[] => [
    { label: "Models", onSelect: () => openAdminTab("modelCatalog") },
    { label: "Delete provider…", danger: true, onSelect: () => void handleDeleteProvider(p.id, p.display_name),
      testId: `provider-delete-${p.id}` },
  ];
  const close = () => {
    if (open) void handleToggleProvider(open.id);
  };

  return (
    <>
      {error ? <p className="admin-panel__error" role="alert">{error}</p> : null}
      <DataTable<any>
        label="Providers"
        testId="providers-table"
        rows={rows}
        rowKey={(p) => p.id}
        selectedKey={expandedProvider ?? null}
        onOpen={(p) => { if (expandedProvider !== p.id) void handleToggleProvider(p.id); }}
        empty={{ text: "No providers configured yet." }}
        rowMenu={(p) => <ActionMenu row={{ objectName: p.display_name || "provider" }} items={menuItems(p)} />}
        columns={providerColumns((p, next) => void toggleActive(p, next))}
      />
      {open ? (
        <ProviderPanel ctx={ctx} open={open} menuItems={menuItems(open)} footerSlot={footerSlot} onFooterSlot={setFooterSlot} onClose={close} />
      ) : null}
    </>
  );
}

function ProviderPanel({ ctx, open, menuItems, footerSlot, onFooterSlot, onClose }: {
  ctx: ProviderTabCtx;
  open: any;
  menuItems: ActionMenuItem[];
  footerSlot: HTMLElement | null;
  onFooterSlot: (slot: HTMLElement | null) => void;
  onClose: () => void;
}) {
  const { handlePullProviderModel, handleRefreshProviderHealth, handleStartLocalRuntime, handleStopLocalRuntime, localBootstrap } = ctx;
  return (
    <SidePanel
      title={open.display_name || "Provider"}
      subtitle={connectionView(open).meta || undefined}
      onClose={onClose}
      testId="provider-panel"
      headerActions={(
        <>
          <StatusLabel label={connectionView(open).status}
            tone={connectionView(open).tone === "attention" ? "attention" : "neutral"} />
          <ActionMenu row={{ objectName: open.display_name || "provider" }} items={menuItems} />
        </>
      )}
      footer={open.driver === LITELLM_GATEWAY_DRIVER
        ? <div ref={onFooterSlot} className="ds-panel__footer-slot" data-testid="provider-panel-footer" />
        : undefined}
    >
      <PanelFooterSlotContext.Provider value={footerSlot}>
      <div className="provider-connection__body">
        <ProviderAuthSection ctx={ctx} provider={open} />
        {open.driver === "ollama" ? (
          <>
            <div className="model-catalog__row-group">
              <button type="button" className="admin-panel__action-btn" onClick={() => void handleStartLocalRuntime(open.id)}>
                Start runtime
              </button>
              <button type="button" className="admin-panel__action-btn" onClick={() => void handleStopLocalRuntime(open.id)}>
                Stop runtime
              </button>
              <button type="button" className="admin-panel__action-btn" onClick={() => void handleRefreshProviderHealth(open.id)}>
                Check health
              </button>
              <button type="button" className="admin-panel__action-btn"
                onClick={() => void handlePullProviderModel(open.id,
                  open.bootstrap_role === "default_anchor" ? localBootstrap?.model_id || "gemma4" : "gemma4")}>
                Pull model
              </button>
            </div>
            <ProvidersLocalBootstrapCard ctx={ctx} />
          </>
        ) : null}
      </div>
      </PanelFooterSlotContext.Provider>
    </SidePanel>
  );
}
