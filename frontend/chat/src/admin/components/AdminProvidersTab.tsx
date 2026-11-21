import { AdminHeaderActions } from "./AdminHeaderSlot";
import { AddProviderForm } from "./providerTab/AddProviderForm";
import { ProvidersList } from "./providerTab/ProvidersList";
import { ProvidersSetupGuideCard } from "./providerTab/ProvidersSetupGuideCard";
import type { ProviderTabCtx } from "./providerTab/types";
import "./modelCatalog/modelCatalog.css";

type AdminProvidersTabProps = {
  ctx: Record<string, unknown>;
};

// Models › Providers: connections and health only, as a full-width table whose
// row opens the connection in a side panel. "Add provider" sits in the
// page header and opens a side panel over the list; what the page is for is in help/admin/providers.md.
export function AdminProvidersTab({ ctx }: AdminProvidersTabProps) {
  const { setShowAddProvider } = ctx as ProviderTabCtx;

  return (
    <div className="model-catalog">
      <AdminHeaderActions>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => setShowAddProvider(true)}
          data-testid="provider-add"
        >
          Add provider
        </button>
      </AdminHeaderActions>
      <ProvidersSetupGuideCard ctx={ctx} />
      <AddProviderForm ctx={ctx} />
      <ProvidersList ctx={ctx} />
    </div>
  );
}
