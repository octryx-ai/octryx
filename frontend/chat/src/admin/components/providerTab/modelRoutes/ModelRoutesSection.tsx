import { useCallback, useEffect, useState } from "react";

import { DataTable, type DataTableColumn } from "../../../../layout/DataTable";
import { FormSection } from "../../../../layout/FormSection";
import { ModelRouteDrawer } from "./ModelRouteDrawer";
import {
  PROVIDER_TYPE_LABELS, draftFromRoute, emptyDraft, loadModelRoutes,
  type ModelRoute, type ModelRouteDraft, type ModelRoutesPayload,
} from "./modelRoutesApi";

const COLUMNS: DataTableColumn<ModelRoute>[] = [
  { key: "alias", header: "Model", render: (route) => route.alias, minWidth: "10rem" },
  { key: "provider", header: "Provider", render: (route) => PROVIDER_TYPE_LABELS[route.provider_type] ?? "—", nowrap: true },
  { key: "upstream", header: "Model ID", render: (route) => route.model || "—", grow: true, clip: "16rem" },
  { key: "class", header: "Data class", render: (route) => route.data_policy_class ?? "—", nowrap: true },
  {
    key: "state", header: "State", nowrap: true,
    render: (route) => (
      <span className={`admin-panel__badge${route.state === "ok" ? " admin-panel__badge--active" : ""}`}
        title={route.problem || undefined}>
        {route.state === "ok" ? "Ready" : "Needs configuration"}
      </span>
    ),
  },
];

// Admin › Models: the bundled LiteLLM's models, one table; a row or "Add model" opens the one side panel.
export function ModelRoutesSection() {
  const [catalog, setCatalog] = useState<ModelRoutesPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<{ draft: ModelRouteDraft; editing: boolean } | null>(null);
  const reload = useCallback(() => {
    setError(null);
    loadModelRoutes().then(setCatalog, (failure: unknown) =>
      setError(failure instanceof Error ? failure.message : String(failure)));
  }, []);
  useEffect(reload, [reload]);
  const add = () => catalog && setOpen({
    draft: emptyDraft({ providerType: Object.keys(catalog.provider_types)[0] ?? "",
      dataClass: catalog.data_policy_classes[0] ?? "" }),
    editing: false,
  });
  return (
    <FormSection title="Models (bundled LiteLLM)" testId="model-routes">
      <div className="admin-panel__form-actions">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={!catalog} onClick={add} data-testid="model-route-add">Add model</button>
      </div>
      {error ? <p className="admin-panel__form-error" role="alert">{error}</p> : null}
      <DataTable label="Models of the bundled LiteLLM" columns={COLUMNS} rows={catalog?.routes ?? []}
        rowKey={(route) => route.alias} loading={!catalog && !error} loadingLabel="models" onRetry={reload}
        selectedKey={open?.editing ? open.draft.alias : null}
        onOpen={(route) => setOpen({ draft: draftFromRoute(route), editing: true })}
        empty={{ text: "No model yet. Add the first one to use it in chats and runs." }} testId="model-routes-table" />
      {open && catalog ? (
        <ModelRouteDrawer draft={open.draft} editing={open.editing} catalog={catalog}
          onClose={() => setOpen(null)} onChanged={reload} />
      ) : null}
    </FormSection>
  );
}
