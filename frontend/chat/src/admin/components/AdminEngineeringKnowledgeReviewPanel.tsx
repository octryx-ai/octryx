import { EngineeringKnowledgeFactDetail } from "./EngineeringKnowledgeFactDetail";
import {
  CLASSIFICATION_OPTIONS,
  optionLabel,
  STATUS_OPTIONS,
  TRUST_OPTIONS,
  VALIDITY_OPTIONS,
  type GraphNode,
} from "./engineeringKnowledgeReviewModel";
import { useReviewFilters, useReviewQueue, type ReviewFilters } from "./useEngineeringKnowledgeReview";

function ReviewHeader({ showHelp, onToggleHelp }: { showHelp: boolean; onToggleHelp: () => void }) {
  return (
    <>
      <div className="admin-panel__section-header">
        <div>
          <div className="admin-panel__eyebrow">Engineering Knowledge Review</div>
          <h3>Review queue</h3>
        </div>
        <button type="button" className="admin-panel__action-btn" onClick={onToggleHelp}>
          Help
        </button>
      </div>
      {showHelp ? (
        <div className="admin-panel__empty-state" style={{ textAlign: "left" }}>
          Review Bronze and Silver engineering facts before they become reusable Gold knowledge. Inspect the evidence
          source, related graph entities, classification, validity, and reviewer history. Promote only facts that are
          evidence-backed and safe to reuse; reject, retract, expire, or mark non-shareable when evidence is weak,
          outdated, or sensitive.
        </div>
      ) : null}
    </>
  );
}

// One filter: its options with "All" (the empty value) first.
function FilterSelect({ value, onChange, options, allKey }: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  allKey: string;
}) {
  return (
    <select className="admin-panel__form-input" value={value} onChange={(event) => onChange(event.target.value)}>
      {options.map((option) => (
        <option key={option || allKey} value={option}>
          {optionLabel(option)}
        </option>
      ))}
    </select>
  );
}

function ReviewToolbar({ filters, loading, onSearch }: { filters: ReviewFilters; loading: boolean; onSearch: () => void }) {
  return (
    <div className="admin-panel__toolbar">
      <input
        className="admin-panel__form-input"
        value={filters.query}
        placeholder="Search package, CVE, repository, source..."
        onChange={(event) => filters.setQuery(event.target.value)}
      />
      <input
        className="admin-panel__form-input"
        value={filters.nodeType}
        placeholder="Node type"
        onChange={(event) => filters.setNodeType(event.target.value)}
      />
      <input
        className="admin-panel__form-input"
        value={filters.source}
        placeholder="Evidence source"
        onChange={(event) => filters.setSource(event.target.value)}
      />
      <FilterSelect value={filters.status} onChange={filters.setStatus} options={STATUS_OPTIONS} allKey="all-status" />
      <FilterSelect value={filters.trustLevel} onChange={filters.setTrustLevel} options={TRUST_OPTIONS} allKey="all-trust" />
      <FilterSelect value={filters.classification} onChange={filters.setClassification} options={CLASSIFICATION_OPTIONS}
        allKey="all-classification" />
      <FilterSelect value={filters.validity} onChange={filters.setValidity} options={VALIDITY_OPTIONS} allKey="all-validity" />
      <button type="button" className="admin-panel__action-btn" onClick={onSearch} disabled={loading}>
        Search
      </button>
    </div>
  );
}

function ReviewCounts({ total, statusCounts, trustCounts }: {
  total: number;
  statusCounts: Record<string, number>;
  trustCounts: Record<string, number>;
}) {
  return (
    <div className="admin-inline-actions">
      <span className="admin-panel__hint">Total {total}</span>
      {Object.entries(statusCounts).map(([key, value]) => (
        <span key={key} className="admin-panel__hint">
          {key}: {value}
        </span>
      ))}
      {Object.entries(trustCounts).map(([key, value]) => (
        <span key={key} className="admin-panel__hint">
          {key}: {value}
        </span>
      ))}
    </div>
  );
}

function ReviewTable({ items, loading, onInspect }: { items: GraphNode[]; loading: boolean; onInspect: (node: GraphNode) => void }) {
  return (
    <div className="admin-panel__table-wrap">
      <table className="admin-panel__table">
        <thead>
          <tr>
            <th>Fact</th>
            <th>Trust</th>
            <th>Status</th>
            <th>Class</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} onClick={() => onInspect(item)} style={{ cursor: "pointer" }}>
              <td>
                <strong>{item.display_name || item.node_key}</strong>
                <div className="admin-panel__hint">
                  {item.node_type} · {item.node_key}
                </div>
              </td>
              <td>{item.trust_level}</td>
              <td>{item.status}</td>
              <td>{item.classification}</td>
              <td>{item.source_refs?.length || 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!loading && items.length === 0 ? (
        <div className="admin-panel__empty-state">No Engineering Knowledge facts match the current filter.</div>
      ) : null}
    </div>
  );
}

export function AdminEngineeringKnowledgeReviewPanel() {
  const filters = useReviewFilters();
  const { payload, selected, loading, busyAction, error, showHelp, setShowHelp, load, inspect, review } = useReviewQueue(filters);

  const items = payload?.items || [];
  const statusCounts = payload?.stats?.status_counts || {};
  const trustCounts = payload?.stats?.trust_counts || {};

  return (
    <div className="admin-panel__stack">
      <ReviewHeader showHelp={showHelp} onToggleHelp={() => setShowHelp((value) => !value)} />
      <ReviewToolbar filters={filters} loading={loading} onSearch={() => void load()} />
      <ReviewCounts total={payload?.total || 0} statusCounts={statusCounts} trustCounts={trustCounts} />
      {error ? <div className="admin-panel__empty-state">{error}</div> : null}
      <div className="admin-form-grid" style={{ alignItems: "start" }}>
        <ReviewTable items={items} loading={loading} onInspect={(item) => void inspect(item)} />
        <div className="admin-panel__form" style={{ minHeight: "420px" }}>
          {selected ? (
            <EngineeringKnowledgeFactDetail selected={selected} busyAction={busyAction} review={review} />
          ) : (
            <div className="admin-panel__empty-state">Select an Engineering Knowledge fact.</div>
          )}
        </div>
      </div>
    </div>
  );
}
