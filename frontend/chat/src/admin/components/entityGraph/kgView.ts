export const TYPE_SLOTS = 8;

// Slots come from the loaded view, never from what is visible, so a type keeps its colour when another is hidden.
export function assignTypeSlots(nodeTypes: Record<string, number> | null | undefined): Map<string, number> {
  const slots = new Map<string, number>();
  const taken = new Set<number>();
  const types = Object.entries(nodeTypes ?? {}).filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  for (const [type] of types) {
    if (taken.size >= TYPE_SLOTS) { slots.set(type, 0); continue; }
    let hash = 0;
    for (const char of type) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
    let slot = (hash % TYPE_SLOTS) + 1;
    while (taken.has(slot)) slot = (slot % TYPE_SLOTS) + 1;
    taken.add(slot);
    slots.set(type, slot);
  }
  return slots;
}

// Next free slot each, so no type already shown changes colour.
export function withTypes(slots: Map<string, number>, types: string[]): Map<string, number> {
  const missing = Array.from(new Set(types)).filter((type) => !slots.has(type)).sort();
  if (!missing.length) return slots;
  const next = new Map(slots);
  const taken = new Set(Array.from(slots.values()));
  for (const type of missing) {
    let slot = 0;
    for (let candidate = 1; candidate <= TYPE_SLOTS; candidate += 1) if (!taken.has(candidate)) { slot = candidate; break; }
    if (slot) taken.add(slot);
    next.set(type, slot);
  }
  return next;
}

export function slotColor(slot: number | undefined): string {
  return slot ? `var(--kg-type-${slot})` : "var(--kg-type-other)";
}

export function neighbourhood(selectedId: string, edges: { source: string; target: string }[]): Set<string> {
  const ids = new Set<string>();
  if (!selectedId) return ids;
  ids.add(selectedId);
  for (const edge of edges) {
    if (edge.source === selectedId) ids.add(edge.target);
    if (edge.target === selectedId) ids.add(edge.source);
  }
  return ids;
}

export type LabelCandidate = { id: string; degree: number; hub: boolean; name: string };

export function labelOrder(candidates: LabelCandidate[], focus: {
  selectedId?: string; hoverId?: string; neighbours?: Set<string>; matches?: Set<string>;
}): string[] {
  const rank = (candidate: LabelCandidate) => {
    if (candidate.id === focus.selectedId) return 0;
    if (candidate.id === focus.hoverId) return 1;
    if (focus.neighbours?.has(candidate.id)) return 2;
    if (focus.matches?.has(candidate.id)) return 3;
    if (candidate.hub) return 4;
    return 5;
  };
  return [...candidates]
    .sort((a, b) => rank(a) - rank(b) || b.degree - a.degree || a.name.localeCompare(b.name) || a.id.localeCompare(b.id))
    .map((candidate) => candidate.id);
}

export type EdgeLook = "idle" | "faint" | "focus" | "dim" | "hover";

export function edgeLook(
  edge: { id: string; source: string; target: string }, selectedId: string, hoverEdgeId = "", faint?: Set<string>,
): EdgeLook {
  if (edge.id === hoverEdgeId) return "hover";
  if (selectedId && (edge.source === selectedId || edge.target === selectedId)) return "focus";
  if (selectedId) return "dim";
  // Lines from the loosely connected ring cross the whole graph, so they stay quiet until hovered or selected.
  return faint && (faint.has(edge.source) || faint.has(edge.target)) ? "faint" : "idle";
}

export const MAX_FOCUS_EDGE_LABELS = 12;
export function showsEdgeLabel(look: EdgeLook, focusEdges: number): boolean {
  return look === "hover" || (look === "focus" && focusEdges <= MAX_FOCUS_EDGE_LABELS);
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

export function countLine(input: {
  shown: number; loaded: number; relationships: number; totalNodes?: number | null; totalEdges?: number | null;
}): string {
  const of = (shown: number, total: number | null | undefined, one: string, many: string) =>
    typeof total === "number" && total !== shown ? `${shown} of ${plural(total, one, many)}` : plural(shown, one, many);
  const entities = typeof input.totalNodes === "number"
    ? of(input.shown, Math.max(input.totalNodes, input.shown), "entity", "entities")
    : of(input.shown, input.loaded, "entity", "entities");
  const relationships = typeof input.totalEdges === "number"
    ? of(input.relationships, Math.max(input.totalEdges, input.relationships), "relationship", "relationships")
    : plural(input.relationships, "relationship", "relationships");
  return `${entities} · ${relationships}`;
}

export type LegendItem = { type: string; slot: number; shown: number; total: number; hidden: boolean };

export function legendItems(
  loaded: { node_type: string }[], hidden: Set<string>, slots: Map<string, number>,
): LegendItem[] {
  const totals = new Map<string, number>();
  for (const node of loaded) totals.set(node.node_type, (totals.get(node.node_type) ?? 0) + 1);
  return Array.from(totals.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([type, total]) => ({ type, slot: slots.get(type) ?? 0, total, shown: hidden.has(type) ? 0 : total, hidden: hidden.has(type) }));
}

export function toggleType(hidden: Set<string>, type: string): Set<string> {
  const next = new Set(hidden);
  if (next.has(type)) next.delete(type);
  else next.add(type);
  return next;
}

export function onlyType(hidden: Set<string>, type: string, all: string[]): Set<string> {
  const alone = all.every((other) => other === type || hidden.has(other)) && !hidden.has(type);
  return alone ? new Set() : new Set(all.filter((other) => other !== type));
}

// One label per entity pair, so labels never sit on top of each other at the same midpoint.
export function edgeLabels(edges: { id: string; source: string; target: string; relation: string; labelled: boolean }[]): Map<string, string> {
  const byPair = new Map<string, { id: string; relations: string[] }>();
  for (const edge of edges) {
    if (!edge.labelled) continue;
    const key = [edge.source, edge.target].sort().join("\u0000");
    const entry = byPair.get(key);
    if (!entry) byPair.set(key, { id: edge.id, relations: [edge.relation] });
    else if (!entry.relations.includes(edge.relation)) entry.relations.push(edge.relation);
  }
  return new Map(Array.from(byPair.values()).map((entry) => [entry.id, entry.relations.join(" · ")]));
}

export type EdgeLabelSpot = { id: string; x1: number; y1: number; x2: number; y2: number; text: string };
export type PlacedEdgeLabel = { x: number; y: number; text: string };
export type LabelObstacle = { x: number; y: number; r: number };

// 11 px text at about 6 px per character.
const LABEL_CHAR_PX = 6;
const LABEL_PAD_PX = 10;
const LABEL_HEIGHT_PX = 18;
const LABEL_GAP_PX = 6;

export function placeEdgeLabels(spots: EdgeLabelSpot[], zoom: number, obstacles: LabelObstacle[] = []): Map<string, PlacedEdgeLabel> {
  const placed = new Map<string, PlacedEdgeLabel>();
  const boxes: { l: number; t: number; r: number; b: number }[] = [];
  const scale = 1 / (zoom || 1);
  const gap = LABEL_GAP_PX * scale;
  for (const spot of spots) {
    const width = (spot.text.length * LABEL_CHAR_PX + LABEL_PAD_PX) * scale;
    const length = Math.hypot(spot.x2 - spot.x1, spot.y2 - spot.y1);
    if (length < width + 2 * gap) continue;
    const x = (spot.x1 + spot.x2) / 2;
    const y = (spot.y1 + spot.y2) / 2;
    const box = { l: x - width / 2, t: y - (LABEL_HEIGHT_PX / 2) * scale, r: x + width / 2, b: y + (LABEL_HEIGHT_PX / 2) * scale };
    const touches = obstacles.some((o) => {
      const nx = Math.max(box.l, Math.min(o.x, box.r));
      const ny = Math.max(box.t, Math.min(o.y, box.b));
      return Math.hypot(o.x - nx, o.y - ny) < o.r + gap;
    });
    if (touches || boxes.some((other) => box.l < other.r && other.l < box.r && box.t < other.b && other.t < box.b)) continue;
    boxes.push(box);
    placed.set(spot.id, { x, y, text: spot.text });
  }
  return placed;
}

export type ClusterLabelSpot = { type: string; x: number; y: number; r: number; size: number; text: string };

export function placeClusterLabels(
  spots: ClusterLabelSpot[], zoom: number, circles: LabelObstacle[] = [],
): Map<string, { left: number; top: number; right: number; bottom: number }> {
  const scale = 1 / (zoom || 1);
  const placed = new Map<string, { left: number; top: number; right: number; bottom: number }>();
  const boxes: { l: number; t: number; r: number; b: number }[] = [];
  const ordered = [...spots].sort((a, b) => b.size - a.size || a.type.localeCompare(b.type));
  for (const spot of ordered) {
    const half = (spot.text.length * 7.5 * scale) / 2;
    const bottom = spot.y - spot.r - 18 + 4 * scale;
    const box = { l: spot.x - half, t: bottom - 14 * scale, r: spot.x + half, b: bottom };
    const hits = boxes.some((other) => box.l < other.r && other.l < box.r && box.t < other.b && other.t < box.b)
      || circles.some((o) => {
        const nx = Math.max(box.l, Math.min(o.x, box.r));
        const ny = Math.max(box.t, Math.min(o.y, box.b));
        return Math.hypot(o.x - nx, o.y - ny) < o.r;
      });
    if (hits) continue;
    boxes.push(box);
    placed.set(spot.type, { left: box.l, top: box.t, right: box.r, bottom: box.b });
  }
  return placed;
}
