// Reading rules of the entity graph: the ranked entity list is the primary reading path, the drawing
// is fitted to its content and keeps labels at a readable on-screen size. Everything is derived from
// the returned nodes and edges; no type, edge or count is invented.

import type { EntityGraphEdge, EntityGraphNode } from "./entityGraphTypes";

export type ViewBox = { x: number; y: number; w: number; h: number };
export type Point = { id: string; x: number; y: number; radius: number };
export type RankedEntity = { id: string; name: string; links: number; selfLinks: number; matched: boolean };

// Minimum on-screen label size (design guide: body small) in CSS pixels.
export const LABEL_PX = 12.5;
const LABEL_MAX_CHARS = 24;

// An edge whose two ends are the same stored entity.
export function isSelfEdge(edge: Pick<EntityGraphEdge, "source" | "target">): boolean {
  return edge.source === edge.target;
}

// Visible relationships per entity; a relationship with the same entity on both ends counts once.
export function linkCounts(edges: Pick<EntityGraphEdge, "source" | "target">[]): Map<string, { links: number; selfLinks: number }> {
  const counts = new Map<string, { links: number; selfLinks: number }>();
  const bump = (id: string, self: boolean) => {
    const entry = counts.get(id) ?? { links: 0, selfLinks: 0 };
    entry.links += 1;
    if (self) entry.selfLinks += 1;
    counts.set(id, entry);
  };
  for (const edge of edges) {
    bump(edge.source, isSelfEdge(edge));
    if (!isSelfEdge(edge)) bump(edge.target, false);
  }
  return counts;
}

// Matches first, then by visible relationships, then by name, so equal inputs always rank equally.
export function rankEntities(
  nodes: Pick<EntityGraphNode, "id" | "display_name">[],
  edges: Pick<EntityGraphEdge, "source" | "target">[],
  matches: Set<string>,
): RankedEntity[] {
  const counts = linkCounts(edges);
  return nodes
    .map((node) => ({
      id: node.id, name: node.display_name || "Unnamed entity",
      links: counts.get(node.id)?.links ?? 0, selfLinks: counts.get(node.id)?.selfLinks ?? 0,
      matched: matches.has(node.id),
    }))
    .sort((a, b) => Number(b.matched) - Number(a.matched) || b.links - a.links
      || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}

export function linkLabel(entity: Pick<RankedEntity, "links" | "selfLinks">): string {
  const base = `${entity.links} ${entity.links === 1 ? "relationship" : "relationships"}`;
  return entity.selfLinks ? `${base}, ${entity.selfLinks} to itself` : base;
}

// Label priority: the selected entity, its neighbours and search matches first, the rest by rank, up
// to `budget` ids. Placement (entityGraphLabels.ts) then skips any label that would collide.
export function labelledIds(
  ranked: RankedEntity[], budget: number, selectedId: string, neighborIds: Set<string>, matches: Set<string>,
): Set<string> {
  const ids = new Set<string>();
  if (selectedId) ids.add(selectedId);
  for (const id of neighborIds) ids.add(id);
  for (const id of matches) ids.add(id);
  for (const entity of ranked) {
    if (ids.size >= budget) break;
    ids.add(entity.id);
  }
  return ids;
}

export function shortLabel(name: string, max = LABEL_MAX_CHARS): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

// The smallest box around every node and its label, padded and never smaller than `minSize`, so a
// small graph is not blown up and a large one fills the drawing on first view.
export function fitViewBox(points: Point[], fallback: ViewBox, padding = 48, minSize = 320): ViewBox {
  if (!points.length) return fallback;
  let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
  for (const point of points) {
    minX = Math.min(minX, point.x - point.radius);
    maxX = Math.max(maxX, point.x + point.radius);
    // Room above for a self-referencing loop.
    minY = Math.min(minY, point.y - point.radius * 2.6);
    // Labels sit below the node.
    maxY = Math.max(maxY, point.y + point.radius + 22);
  }
  // Labels are wider than nodes, so the sides get twice the padding.
  let w = maxX - minX + padding * 4;
  let h = maxY - minY + padding * 2;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  w = Math.max(w, minSize);
  h = Math.max(h, minSize * 0.6);
  return { x: cx - w / 2, y: cy - h / 2, w, h };
}

// User units per CSS pixel of an SVG drawn with the default "xMidYMid meet".
export function unitsPerPixel(box: ViewBox, widthPx: number, heightPx: number): number {
  if (!(widthPx > 0) || !(heightPx > 0)) return box.w / 1000;
  return Math.max(box.w / widthPx, box.h / heightPx);
}

// Font size in user units that renders as at least LABEL_PX on screen at the current zoom.
export function labelFontSize(box: ViewBox, widthPx: number, heightPx: number, px = LABEL_PX): number {
  return px * unitsPerPixel(box, widthPx, heightPx);
}

// A loop drawn above a node for a relationship whose two ends are the same entity.
export function selfLoopPath(point: Pick<Point, "x" | "y" | "radius">): string {
  const { x, y, radius: r } = point;
  const start = `${(x - r * 0.6).toFixed(1)} ${(y - r * 0.8).toFixed(1)}`;
  const end = `${(x + r * 0.6).toFixed(1)} ${(y - r * 0.8).toFixed(1)}`;
  const c1 = `${(x - r * 2.2).toFixed(1)} ${(y - r * 3.2).toFixed(1)}`;
  const c2 = `${(x + r * 2.2).toFixed(1)} ${(y - r * 3.2).toFixed(1)}`;
  return `M ${start} C ${c1} ${c2} ${end}`;
}

export function isSelfRelation(detail: { id: string }, relation: { peer_id: string }): boolean {
  return relation.peer_id === detail.id;
}

// Facts that are not already shown as a relationship (same statement from the same evidence).
export function detailClaims<C extends { statement: string; evidence_key?: string }>(
  detail: { claims: C[]; relations: Array<{ description: string; evidence_key?: string }> },
): C[] {
  const shown = new Set(detail.relations.map((relation) => `${relation.evidence_key ?? ""}\u0000${relation.description}`));
  return detail.claims.filter((claim) => !shown.has(`${claim.evidence_key ?? ""}\u0000${claim.statement}`));
}
