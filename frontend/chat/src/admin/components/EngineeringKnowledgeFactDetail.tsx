// Detail of the selected Engineering Knowledge fact: lifecycle, review actions, evidence and relations.
import { lifecycleField, sourceRefLabel, type GraphNode } from "./engineeringKnowledgeReviewModel";

type Review = (action: string, reason: string, extra?: Record<string, unknown>) => Promise<void>;

/** Promote, reject, retract, expire or mark the fact non-shareable; all disabled while an action runs. */
function FactReviewActions({ busyAction, review }: { busyAction: string; review: Review }) {
  return (
    <>
        <div className="admin-inline-actions">
          <button
            type="button"
            className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={Boolean(busyAction)}
            onClick={() => void review("promote", "Promoted from Engineering Knowledge review.", { trust_level: "gold" })}
          >
            Promote Gold
          </button>
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={Boolean(busyAction)}
            onClick={() => void review("reject", "Rejected from Engineering Knowledge review.")}
          >
            Reject
          </button>
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={Boolean(busyAction)}
            onClick={() => void review("retract", "Retracted from Engineering Knowledge review.")}
          >
            Retract
          </button>
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={Boolean(busyAction)}
            onClick={() => void review("expire", "Expired from Engineering Knowledge review.")}
          >
            Expire
          </button>
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={Boolean(busyAction)}
            onClick={() => void review("mark_non_shareable", "Marked non-shareable from review.")}
          >
            Non-shareable
          </button>
        </div>
    </>
  );
}

/** The fact's source references and its related graph facts. */
function FactEvidenceAndRelations({ selected }: { selected: GraphNode }) {
  return (
    <>
        <h4>Evidence</h4>
        <div className="admin-panel__stack">
          {(selected.source_refs || []).map((ref, index) => (
            <div key={`${ref.source_type}:${ref.source_ref}:${index}`} className="admin-panel__empty-state">
              <strong>{ref.title || sourceRefLabel(ref)}</strong>
              <div>{sourceRefLabel(ref)}</div>
              {ref.url ? <div style={{ wordBreak: "break-all" }}>{ref.url}</div> : null}
              {ref.observed_at ? <div>{ref.observed_at}</div> : null}
            </div>
          ))}
          {selected.source_refs?.length ? null : <div className="admin-panel__empty-state">No source refs.</div>}
        </div>
        <h4>Relations</h4>
        <div className="admin-panel__stack">
          {(selected.related_edges || []).map((edge) => (
            <div key={edge.id} className="admin-panel__hint">
              {edge.direction} {edge.edge_type}: {edge.related_node?.display_name || edge.related_node?.node_key}
            </div>
          ))}
          {selected.related_edges?.length ? null : <div className="admin-panel__hint">No related graph facts.</div>}
        </div>
    </>
  );
}

export function EngineeringKnowledgeFactDetail({
  selected,
  busyAction,
  review,
}: {
  selected: GraphNode;
  busyAction: string;
  review: Review;
}) {
  return (
    <>
      <div className="admin-panel__section-header">
        <div>
          <div className="admin-panel__eyebrow">{selected.node_type}</div>
          <h3>{selected.display_name || selected.node_key}</h3>
        </div>
      </div>
      <p className="admin-panel__hint">{selected.summary || "No summary."}</p>
      <div className="admin-inline-actions">
        <span className="admin-panel__hint">status: {selected.status}</span>
        <span className="admin-panel__hint">trust: {selected.trust_level}</span>
        <span className="admin-panel__hint">class: {selected.classification}</span>
      </div>
      {lifecycleField(selected, "reason") ? (
        <div className="admin-panel__empty-state">
          <strong>Lifecycle</strong>
          <div>state: {lifecycleField(selected, "state") || selected.status}</div>
          <div>reason: {lifecycleField(selected, "reason")}</div>
          {lifecycleField(selected, "source") ? <div>source: {lifecycleField(selected, "source")}</div> : null}
          {lifecycleField(selected, "event_ref") ? (
            <div>event: {lifecycleField(selected, "event_ref")}</div>
          ) : null}
          {lifecycleField(selected, "changed_at") ? (
            <div>changed: {lifecycleField(selected, "changed_at")}</div>
          ) : null}
        </div>
      ) : null}
      <FactReviewActions busyAction={busyAction} review={review} />
      <FactEvidenceAndRelations selected={selected} />
    </>
  );
}
