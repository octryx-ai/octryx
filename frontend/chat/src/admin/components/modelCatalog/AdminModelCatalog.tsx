import { useEffect, useRef } from "react";

import { ModelCatalogDrawer } from "./ModelCatalogDrawer";
import { ModelCatalogSyncDrawer } from "./ModelCatalogSyncDrawer";
import { CatalogBar, CatalogTable } from "./ModelCatalogParts";
import { filterRows, sortRows } from "./modelCatalogContract";
import type { CatalogRow } from "./modelCatalogContract";
import { modelToFocus } from "./modelFocus";
import { useModelCatalog } from "./useModelCatalog";
import "./modelCatalog.css";
import { LoadingState } from "../../../layout/LoadingState";

// Runtime → Models → Model catalog: every callable model, one row each.
export function AdminModelCatalog() {
  const { catalog, setCatalog, loadError, categories, providerId, setProviderId, status, setStatus, scope, setScope, openId, setOpenId, syncing, setSyncing, reload } = useModelCatalog();

  // A Problems link (?model=<id>) opens that model once and scrolls its row into view.
  const focused = useRef(false);
  useEffect(() => {
    if (focused.current || !catalog) return;
    const target = modelToFocus(catalog.models, typeof window === "undefined" ? "" : window.location.search);
    if (!target) return;
    focused.current = true;
    // A linked model that the default view hides is shown with all models, so its row is there to scroll to.
    if (!filterRows([target], "", "", "inUse").length) setScope("all");
    setOpenId(target.id);
    if (typeof document !== "undefined") {
      document.querySelector(`[data-testid="catalog-row-${target.catalogKey}"]`)?.scrollIntoView?.({ block: "center" });
    }
  }, [catalog, setOpenId, setScope]);

  const open = catalog?.models.find((row) => row.id === openId) ?? null;
  const replaceRow = (saved: CatalogRow) =>
    setCatalog((current) => current && { ...current, models: current.models.map((row) => (row.id === saved.id ? saved : row)) });
  const rows = catalog ? sortRows(filterRows(catalog.models, providerId, status, scope)) : [];
  const inUseCount = catalog ? filterRows(catalog.models, "", "", "inUse").length : 0;
  // What the default view leaves out under the chosen filters, offered in one click.
  const hidden = catalog && scope === "inUse" ? filterRows(catalog.models, providerId, status, "all").length - rows.length : 0;

  return (
    <div className="model-catalog">
      <CatalogBar catalog={catalog} scope={scope} setScope={setScope} inUseCount={inUseCount} providerId={providerId} setProviderId={setProviderId}
        status={status} setStatus={setStatus} onSync={() => setSyncing(true)} />
      {loadError ? <p className="admin-panel__error" role="alert">{loadError}</p> : null}
      {!catalog && !loadError ? <LoadingState label="the model catalog" /> : null}
      {catalog ? (
        <CatalogTable catalog={catalog} rows={rows} categories={categories} openId={openId} setOpenId={setOpenId} scope={scope}
          filtered={Boolean(providerId || status)} hidden={hidden} onShowAll={() => setScope("all")} />
      ) : null}
      {open && catalog ? (
        <ModelCatalogDrawer key={open.id} row={open} levels={catalog.levels} categories={categories}
          onClose={() => setOpenId(null)} onSaved={replaceRow} />
      ) : null}
      {syncing ? <ModelCatalogSyncDrawer onClose={() => setSyncing(false)} onChanged={reload} /> : null}
    </div>
  );
}
