// Detail pane for a selected entity, docked beside the graph (desktop) or below its neighbourhood (phone), so
// the graph stays in view. Focus moves to the heading on open; Close (or Escape, handled by the stage) returns
// to the graph. Expand loads the entity's neighbourhood as the next step of the focus trail.

import { useEffect, useMemo, useRef } from "react";
import type { EntityGraphEdge, EntityNodeDetail } from "./entityGraphTypes";
import { detailClaims } from "./entityGraphReading";
import { detailScopeLine, humanizeRelation, incidentEdgeCount, relationRows, trustLabels } from "./entityGraphDetailModel";
import { EntityGraphCitation } from "./EntityGraphCitation";
import { EntityGraphDetailRelations } from "./EntityGraphDetailRelations";
import "./entity-graph-detail.css";

type Props = {
  workspaceId: string;
  entityId: string;
  // The name from the current view, shown while the stored details load.
  entityName: string;
  detail: EntityNodeDetail | null;
  loading: boolean;
  viewEdges: EntityGraphEdge[];
  viewIds: Set<string>;
  onSelect: (nodeId: string) => void;
  onFocusNode: (nodeId: string) => void;
  onBack: () => void;
  // Knowledge → Explore: opens Search with the entity's name.
  onSearchFor?: (name: string) => void;
  // Adds the entity's neighbourhood to the view (additive Expand); without it, Expand loads the neighbourhood.
  onExpand?: (nodeId: string) => void;
  // The colour of the entity's type on the canvas (kgView.slotColor).
  typeColor?: string;
};

function DetailBody({ detail, workspaceId, viewEdges, viewIds, onSelect, onFocusNode, typeColor }:
  Pick<Props, "workspaceId" | "viewEdges" | "viewIds" | "onSelect" | "onFocusNode" | "typeColor"> & { detail: EntityNodeDetail }) {
  const rows = useMemo(() => relationRows(detail, viewEdges, viewIds), [detail, viewEdges, viewIds]);
  const labels = trustLabels(detail.trust_level, detail.status);
  const claims = detailClaims(detail);
  return <>
    <div className="entity-graph__detail-meta">
      {detail.node_type && detail.node_type !== "entity" ? <span className="entity-graph__chip">
        <span className="entity-graph__type-dot" style={{ backgroundColor: typeColor ?? "var(--kg-type-other)" }} />
        {" "}{detail.node_type}
      </span> : null}
      <span className="entity-graph__chip">{labels.trust}</span>
      {labels.status ? <span className="entity-graph__chip entity-graph__chip--warn">{labels.status}</span> : null}
    </div>
    <p className="entity-graph__scope">{detailScopeLine(detail, incidentEdgeCount(detail.id, viewEdges))}</p>
    {detail.description ? <p className="entity-graph__detail-description">{detail.description}</p> : null}
    <h4>Relationships</h4>
    <EntityGraphDetailRelations rows={rows} workspaceId={workspaceId} onSelect={onSelect} onFocusNode={onFocusNode} />
    {detail.aliases.length ? <>
      <h4>Aliases</h4>
      <p className="entity-graph__aliases">{detail.aliases.slice(0, 12).join(" · ")}</p>
    </> : null}
    {claims.length ? <>
      <h4>Other facts ({claims.length})</h4>
      <ul className="entity-graph__relations">
        {claims.map((claim, index) => <li key={`${claim.claim_type}-${index}`} className="entity-graph__relation">
          <p className="entity-graph__relation-statement">
            <span className="entity-graph__relation-type" title={claim.claim_type}>{humanizeRelation(claim.claim_type)}</span>
            {" · "}{claim.statement}
          </p>
          <EntityGraphCitation evidence={claim} workspaceId={workspaceId} />
        </li>)}
      </ul>
    </> : null}
  </>;
}

export function AdminEntityGraphDetailPanel(props: Props) {
  const { entityId, entityName, detail, loading, onFocusNode, onExpand, onBack, onSearchFor } = props;
  const heading = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => {
    heading.current?.focus?.({ preventScroll: true });
  }, [entityId]);
  const current = detail && detail.id === entityId ? detail : null;
  const name = current?.display_name || entityName || "Unnamed entity";
  return (
    <section className="entity-graph__detail" aria-label={`${name} details`} aria-busy={loading || undefined}>
      <div className="entity-graph__detail-header">
        <h3 ref={heading} tabIndex={-1} className="entity-graph__detail-title">{name}</h3>
        <div className="entity-graph__detail-actions">
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
            title="Add this entity's neighbourhood to the graph (double-click on the graph does the same)"
            onClick={() => (onExpand ? onExpand(entityId) : onFocusNode(entityId))}>
            Expand
          </button>
          {onSearchFor ? <button type="button" className="admin-panel__action-btn" onClick={() => onSearchFor(name)}>
            Search for this
          </button> : null}
        </div>
        <button type="button" className="kg-detail__close" aria-label="Close details" title="Close (Esc)" onClick={onBack}>
          <span className="entity-graph__back-wide" aria-hidden="true">×</span>
          <span className="entity-graph__back-narrow">← Back to results</span>
        </button>
      </div>
      {loading ? <p className="admin-panel__note">Loading entity…</p>
        : current ? <DetailBody {...props} detail={current} />
          : <p className="admin-panel__note">Details for this entity could not be loaded. Go back to the graph, or select the entity again.</p>}
    </section>
  );
}
