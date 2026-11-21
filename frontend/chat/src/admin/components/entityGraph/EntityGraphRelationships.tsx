import type { EntityGraphPayload } from "./entityGraphTypes";
import { EntityGraphCitation } from "./EntityGraphCitation";
import { humanizeRelation } from "./entityGraphDetailModel";
import { isSelfEdge } from "./entityGraphReading";

// Every relationship in this view with its statement and source, collapsed by default: the entity
// list and the detail pane are the reading path, this is the complete inventory. A relationship whose
// two ends are the same stored entity is stated as such: the extraction merged both names into one
// entity.
export function EntityGraphRelationships({ payload, onSelect }: { payload: EntityGraphPayload; onSelect: (id: string) => void }) {
  if (!payload.edges.length) return null;
  const names = new Map(payload.nodes.map((node) => [node.id, node.display_name]));
  const entity = (id: string) => <button type="button" className="entity-graph__link" onClick={() => onSelect(id)}>{names.get(id) || "Entity"}</button>;
  return <details className="entity-graph__all-relations">
    <summary>All relationships in this view ({payload.edges.length})</summary>
    <div className="admin-panel__table-wrap"><table className="admin-panel__table">
      <thead><tr><th>Entities</th><th>Relationship and evidence</th></tr></thead>
      <tbody>{payload.edges.map((edge) => <tr key={edge.id}>
        <td>{isSelfEdge(edge)
          ? <>{entity(edge.source)} <span className="entity-graph__self">refers to itself (same entity on both ends)</span></>
          : <>{entity(edge.source)}{" → "}{entity(edge.target)}</>}</td>
        <td><strong title={edge.edge_type}>{humanizeRelation(edge.edge_type)}</strong><p>{edge.description}</p>
          <EntityGraphCitation evidence={edge} workspaceId={payload.workspace_id} /></td>
      </tr>)}</tbody>
    </table></div>
  </details>;
}
