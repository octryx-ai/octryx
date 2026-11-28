import { AdminHeaderActions } from "./AdminHeaderSlot";
import { AddProviderForm } from "./providerTab/AddProviderForm";
import { ModelRoutesSection } from "./providerTab/modelRoutes/ModelRoutesSection";
import { ProvidersList } from "./providerTab/ProvidersList";
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
          className="admin-panel__action-btn"
          onClick={() => setShowAddProvider(true)}
          data-testid="provider-add"
        >
          Add provider
        </button>
      </AdminHeaderActions>
      <AddProviderForm ctx={ctx} />
      <ModelRoutesSection />
      <ProvidersList ctx={ctx} />
    </div>
  );
}
