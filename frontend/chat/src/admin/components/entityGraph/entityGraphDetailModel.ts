// Reading model of the entity detail pane: one trust label, a scope line that separates the stored
// neighbourhood from what this view shows, and relationship rows matched to the view's edges. Nothing
// is invented: every row is a stored relationship, every "in this view" mark an exact edge match.

import type { EntityGraphEdge, EntityNodeDetail, EntityNodeRelation } from "./entityGraphTypes";

export type RelationKind = "out" | "in" | "self";

export type RelationRow = {
  key: string;
  kind: RelationKind;
  peerId: string;
  peerName: string;
  peerInView: boolean;
  relation: string;
  code: string;
  inView: boolean;
  source: EntityNodeRelation;
};

// `HAS_PROPERTIES_UNDER` → "has properties under"; the raw code stays available to the caller.
export function humanizeRelation(code: string): string {
  const text = (code || "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_\-\s]+/g, " ")
    .trim()
    .toLowerCase();
  return text || "unnamed relationship";
}

function sentenceCase(value: string): string {
  const text = humanizeRelation(value);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// One trust label. Status is shown only when it says something the trust label does not.
export function trustLabels(trustLevel: string, status: string): { trust: string; status: string | null } {
  const trust = (trustLevel || "").trim().toLowerCase();
  const label = !trust ? "Trust not stated" : trust === "extracted" ? "Extracted · not reviewed" : sentenceCase(trust);
  const state = (status || "").trim().toLowerCase();
  return { trust: label, status: state && state !== trust && state !== "active" ? sentenceCase(state) : null };
}

export function incidentEdgeCount(entityId: string, edges: Pick<EntityGraphEdge, "source" | "target">[]): number {
  return edges.filter((edge) => edge.source === entityId || edge.target === entityId).length;
}

export function detailScopeLine(detail: Pick<EntityNodeDetail, "relations" | "truncated">, shownInView: number): string {
  // The node endpoint returns the readable, bounded neighbourhood only; it never attests a stored total.
  const available = detail.relations.length;
  return `${available} available ${available === 1 ? "relationship" : "relationships"} in this neighbourhood`
    + `${detail.truncated ? " (bounded, more may exist)" : ""} · ${shownInView} shown in the current view`;
}

// Available (readable, bounded) relationships as rows. A row is "in this view" only when a shown edge has the same ends in
// the same direction, the same relation and statement (and evidence, when both carry it); each shown
// edge accounts for one row at most. Rows in this view come first, otherwise the returned order holds.
export function relationRows(
  detail: Pick<EntityNodeDetail, "id" | "relations">, viewEdges: EntityGraphEdge[], viewIds: Set<string>,
): RelationRow[] {
  const unused = new Set(viewEdges.filter((edge) => edge.source === detail.id || edge.target === detail.id));
  const rows = detail.relations.map((relation, index) => {
    const kind: RelationKind = relation.peer_id === detail.id ? "self" : relation.direction === "in" ? "in" : "out";
    const [source, target] = kind === "in" ? [relation.peer_id, detail.id] : [detail.id, relation.peer_id];
    const edge = [...unused].find((candidate) => candidate.source === source && candidate.target === target
      && candidate.edge_type === relation.edge_type && candidate.description === relation.description
      && (!relation.evidence_key || !candidate.evidence_key || candidate.evidence_key === relation.evidence_key));
    if (edge) unused.delete(edge);
    return {
      key: `${relation.peer_id}-${relation.edge_type}-${index}`, kind, peerId: relation.peer_id,
      peerName: relation.peer_name || "Unnamed entity", peerInView: viewIds.has(relation.peer_id),
      relation: humanizeRelation(relation.edge_type), code: relation.edge_type, inView: Boolean(edge), source: relation,
    };
  });
  return [...rows.filter((row) => row.inView), ...rows.filter((row) => !row.inView)];
}
