import { useEffect, useState } from "react";

import { StatusLabel } from "../../../layout/StatusLabel";
import { useAdminNavigation } from "../../adminNavigation";
import { TimeText } from "../../utils/TimeText";
import "../modelCatalog/modelCatalog.css";
import {
  availableText,
  loadModelsOverview,
  priceText,
  providerModelsLine,
  providerState,
  workspaceChanges,
  type ModelsOverview,
} from "./modelsOverviewModel";

// Global › Models: the providers (each set up the same way), the models a workspace can pick from, and every
// narrowing a workspace made. Read only; edits open the page that owns them (Providers, Catalog, Defaults).
export function AdminModelsOverview() {
  const { openAdminTab } = useAdminNavigation();
  const [view, setView] = useState<ModelsOverview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    loadModelsOverview()
      .then((data) => !cancelled && setView(data))
      .catch((reason: unknown) => !cancelled && setError(reason instanceof Error ? reason.message : "The overview could not be loaded."));
    return () => { cancelled = true; };
  }, []);

  if (error) return <p className="admin-panel__error" role="alert">{error}</p>;
  if (!view) return <p className="model-catalog__sub">Loading models…</p>;

  return (
    <div className="model-catalog" data-testid="models-overview">
      <p className="model-catalog__sub">
        Global · applies to all {view.workspaces} workspaces. Providers deliver the models; every provider is set up the
        same way. A workspace can only pick from what is switched on here.
      </p>

      <OverviewProviders providers={view.providers} openAdminTab={openAdminTab} />

      <OverviewModels view={view} openAdminTab={openAdminTab} />
    </div>
  );
}

type OpenAdminTab = ReturnType<typeof useAdminNavigation>["openAdminTab"];

// Every provider, set up the same way: its driver and endpoint, what it loaded, and its state.
function OverviewProviders({ providers, openAdminTab }: { providers: ModelsOverview["providers"]; openAdminTab: OpenAdminTab }) {
  return (
    <section aria-label="Providers" className="models-overview__providers">
      <div className="model-catalog__bar">
        <h3 className="models-overview__heading">Providers</h3>
        <button type="button" className="admin-panel__action-btn" onClick={() => openAdminTab("providers")}>Add or edit providers</button>
      </div>
      {providers.map((provider) => {
        const state = providerState(provider);
        return (
          <article className="models-overview__provider" key={provider.id} data-testid={`overview-provider-${provider.id}`}>
            <div className="models-overview__provider-main">
              <div className="model-catalog__name">{provider.name}</div>
              <div className="model-catalog__sub">{[provider.driver, provider.endpoint].filter(Boolean).join(" · ")}</div>
              <div className="model-catalog__sub">
                {providerModelsLine(provider)}
                {provider.loaded_at && provider.state !== "off" ? <> · loaded <TimeText value={provider.loaded_at} /></> : null}
              </div>
              {provider.error ? <div className="admin-panel__error">{provider.error}</div> : null}
            </div>
            <StatusLabel label={state.label} tone={state.tone} />
          </article>
        );
      })}
    </section>
  );
}

// The models a workspace can choose, with their price, where they are available and what the workspaces changed.
function OverviewModels({ view, openAdminTab }: { view: ModelsOverview; openAdminTab: OpenAdminTab }) {
  return (
    <section aria-label="Models">
      <div className="model-catalog__bar">
        <h3 className="models-overview__heading">Models workspaces can choose</h3>
        <span className="model-catalog__sub">Platform default: {view.platform_default || "–"}</span>
        <button type="button" className="admin-panel__action-btn" onClick={() => openAdminTab("modelOrder")}>Change default</button>
      </div>
      <table className="admin-panel__table model-catalog__table work-cards" data-testid="overview-models">
        <thead>
          <tr><th>Model</th><th>Provider</th><th>Price in / out per 1M</th><th>Available in</th><th>Workspace changes</th></tr>
        </thead>
        <tbody>
          {view.models.map((model) => {
            const price = priceText(model);
            return (
              <tr key={model.key}>
                <td data-label="Model">
                  <div className="model-catalog__name">{model.label}</div>
                  {model.platform_default ? <div className="model-catalog__sub">Platform default</div> : null}
                </td>
                <td data-label="Provider">{model.provider}</td>
                <td data-label="Price in / out">
                  {price ?? (
                    <span>
                      <span className="model-catalog__off">Price missing · </span>
                      <button type="button" className="sk-link" onClick={() => openAdminTab("modelCatalog")}>add</button>
                    </span>
                  )}
                </td>
                <td data-label="Available in" className={model.provider_off ? "model-catalog__off" : ""}>{availableText(model, view.workspaces)}</td>
                <td data-label="Workspace changes" className={model.off_in.length || model.default_in.length ? "" : "model-catalog__off"}>{workspaceChanges(model)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="model-catalog__sub">
        Prices come from the provider when it reports them; otherwise you set them once in the Catalog. Usage and
        budgets use these prices.
      </p>
    </section>
  );
}
