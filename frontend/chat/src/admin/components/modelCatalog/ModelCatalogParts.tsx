import { categoryLabel } from "./contentCategories";
import { CAPABILITY_KEYS, CAPABILITY_LABELS, levelLabel, levelTone, orderTag, priceText, statusView, usedByText } from "./modelCatalogContract";
import type { Catalog, CatalogRow, CatalogScope, StatusFilter } from "./modelCatalogContract";
import type { ContentCategory } from "../providerTab/litellmGatewayApprovedCategories";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";

// The scope tabs, the provider and status filters, and "Sync from providers".
export function CatalogBar({ catalog, scope, setScope, inUseCount, providerId, setProviderId, status, setStatus, onSync }: {
  catalog: Catalog | null;
  scope: CatalogScope;
  setScope: (scope: CatalogScope) => void;
  inUseCount: number;
  providerId: string;
  setProviderId: (value: string) => void;
  status: StatusFilter;
  setStatus: (value: StatusFilter) => void;
  onSync: () => void;
}) {
  return (
    <div className="model-catalog__bar">
      <div className="model-catalog__row-group">
        <SegmentedTabs label="Models shown" idPrefix="catalog-scope" value={scope} testId="catalog-scope" size="small"
          tabs={[{ key: "inUse", label: "Used or enabled", count: inUseCount, testId: "catalog-scope-in-use" },
            { key: "all", label: "All models", count: catalog?.models.length ?? 0, testId: "catalog-scope-all" }]}
          onChange={(key) => setScope(key as CatalogScope)} />
        <select className="admin-users__toolbar-select" value={providerId} aria-label="Provider" data-testid="catalog-filter-provider"
          onChange={(event) => setProviderId(event.target.value)}>
          <option value="">All providers</option>
          {catalog?.providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.displayName}</option>)}
        </select>
        <select className="admin-users__toolbar-select" value={status} aria-label="Status" data-testid="catalog-filter-status"
          onChange={(event) => setStatus(event.target.value as StatusFilter)}>
          <option value="">Any status</option>
          <option value="on">Enabled</option>
          <option value="off">Not enabled</option>
          <option value="issue">Needs attention</option>
        </select>
      </div>
      <button type="button" className="admin-panel__action-btn" data-testid="catalog-sync" onClick={onSync}>
        Sync from providers
      </button>
    </div>
  );
}

// One model: name and provider, capabilities, clearance, approved categories, price, use and status.
export function CatalogTableRow({ row, catalog, categories, openId, setOpenId }: {
  row: CatalogRow;
  catalog: Catalog;
  categories: ContentCategory[];
  openId: string | null;
  setOpenId: (id: string) => void;
}) {
  const view = statusView(row);
  const caps = CAPABILITY_KEYS.filter((key) => row.capabilities[key]);
  return (
    <tr className={`${row.enabled ? "" : "admin-panel__row--inactive"}${row.id === openId ? " model-catalog__row--focused" : ""}`.trim()} data-testid={`catalog-row-${row.catalogKey}`}
      tabIndex={0} onClick={() => setOpenId(row.id)}
      onKeyDown={(event) => { if (event.key === "Enter") setOpenId(row.id); }}>
      <td data-label="Model">
        <div className="model-catalog__name">{row.displayName}</div>
        <div className="model-catalog__sub">{row.provider.displayName}</div>
      </td>
      <td data-label="Capabilities">
        <div className="model-catalog__chips">
          {caps.length ? caps.map((key) => (
            <span key={key} className="admin-policy-chip admin-policy-chip--secondary">{CAPABILITY_LABELS[key]}</span>
          )) : <span className="model-catalog__off">None</span>}
        </div>
      </td>
      <td data-label="Cleared up to">
        {row.clearedUpTo
          ? <span className={`work-badge work-badge--${levelTone(row.clearedUpTo, catalog.levels)}`}>{levelLabel(row.clearedUpTo)}</span>
          : <span className="model-catalog__off">—</span>}
      </td>
      <td data-label="Approved for">
        {row.approvedFor.length ? (
          <div className="model-catalog__chips">
            {row.approvedFor.map((id) => <span key={id} className="admin-policy-chip">{categoryLabel(categories, id)}</span>)}
          </div>
        ) : <span className="model-catalog__off">—</span>}
      </td>
      <td data-label="Price">{priceText(row)}</td>
      <td data-label="Used by">
        {row.usedBy ? usedByText(row) : <span className="model-catalog__off">None</span>}
        {row.orderPosition ? <span className="model-catalog__tag"> {orderTag(row)}</span> : null}
      </td>
      <td data-label="Status">
        <span className={`work-badge work-badge--${view.tone}`} title={view.title}>{view.label}</span>
      </td>
    </tr>
  );
}

// The catalog table: one row per shown model, the empty line and the offer to show the hidden models.
export function CatalogTable({ catalog, rows, categories, openId, setOpenId, scope, filtered, hidden, onShowAll }: {
  catalog: Catalog;
  rows: CatalogRow[];
  categories: ContentCategory[];
  openId: string | null;
  setOpenId: (id: string) => void;
  scope: CatalogScope;
  filtered: boolean;
  hidden: number;
  onShowAll: () => void;
}) {
  return (
    <table className="admin-panel__table model-catalog__table" data-testid="catalog-table">
      <thead>
        <tr>
          <th>Model</th><th>Capabilities</th><th>Cleared up to</th><th>Approved for</th>
          <th>Price / 1M (in · out)</th><th>Used by</th><th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <CatalogTableRow key={row.id} row={row} catalog={catalog} categories={categories} openId={openId} setOpenId={setOpenId} />
        ))}
        {!rows.length ? (
          <tr><td colSpan={7} className="admin-panel__empty">
            {scope === "inUse" && !filtered ? "No model is used or enabled yet." : "No model matches the filters."}
          </td></tr>
        ) : null}
        {hidden > 0 ? (
          <tr className="model-catalog__more"><td colSpan={7}>
            <button type="button" className="ds-link-button" data-testid="catalog-show-all" onClick={onShowAll}>
              Show {hidden} more {hidden === 1 ? "model" : "models"} (off or at a disabled provider)
            </button>
          </td></tr>
        ) : null}
      </tbody>
    </table>
  );
}
