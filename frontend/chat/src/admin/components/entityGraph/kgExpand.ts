import type { Placed } from "./kgLayout";
import { nodeRadius } from "./kgLayout";

/** The server's limit for `current_node_ids` (comma-separated). */
export const MAX_CURRENT_IDS_CHARS = 12000;
export const EXPAND_MAX_NODES = 30;

/** Over the server's limit `priority` ids go first; the server may then return an entity already shown,
 * which the merge ignores. */
export function currentIdsParam(all: string[], priority: string[] = [], limit = MAX_CURRENT_IDS_CHARS): string {
  const seen = new Set<string>();
  const ordered: string[] = [];
  for (const id of [...priority, ...all]) {
    if (!id || seen.has(id)) continue;
    seen.add(id);
    ordered.push(id);
  }
  let out = "";
  for (const id of ordered) {
    const next = out ? `${out},${id}` : id;
    if (next.length > limit) break;
    out = next;
  }
  return out;
}

const GAP = 22;

export function placeAround(
  centre: { x: number; y: number; r: number }, items: { id: string; node_type: string; degree: number }[],
  occupied: { x: number; y: number; r: number }[],
): Map<string, Placed> {
  const placed = new Map<string, Placed>();
  const taken = occupied.map((circle) => ({ ...circle }));
  const ordered = [...items].sort((a, b) => a.node_type.localeCompare(b.node_type) || b.degree - a.degree || a.id.localeCompare(b.id));
  let ring = 0;
  let index = 0;
  while (index < ordered.length && ring < 40) {
    const radius = centre.r + 90 + ring * 64;
    const slots = Math.max(6, Math.floor((2 * Math.PI * radius) / (2 * 14 + GAP + 40)));
    for (let slot = 0; slot < slots && index < ordered.length; slot += 1) {
      const node = ordered[index];
      const r = nodeRadius(node.degree);
      const angle = (slot / slots) * 2 * Math.PI - Math.PI / 2 + ring * 0.37;
      const x = centre.x + Math.cos(angle) * radius;
      const y = centre.y + Math.sin(angle) * radius;
      if (taken.some((other) => Math.hypot(other.x - x, other.y - y) < other.r + r + GAP)) continue;
      taken.push({ x, y, r });
      placed.set(node.id, { x, y, r, cluster: node.node_type, hub: false });
      index += 1;
    }
    ring += 1;
  }
  return placed;
}

export type Additions<N, E> = { nodes: N[]; edges: E[]; positions: Map<string, Placed> };

export function mergeAdditions<N extends { id: string }, E extends { id: string }>(
  base: { nodes: N[]; edges: E[] }, current: Additions<N, E>, incoming: { nodes: N[]; edges: E[] }, positions: Map<string, Placed>,
): Additions<N, E> {
  const nodeIds = new Set(base.nodes.concat(current.nodes).map((node) => node.id));
  const edgeIds = new Set(base.edges.concat(current.edges).map((edge) => edge.id));
  const merged = new Map(current.positions);
  positions.forEach((at, id) => { if (!nodeIds.has(id)) merged.set(id, at); });
  return {
    nodes: current.nodes.concat(incoming.nodes.filter((node) => !nodeIds.has(node.id))),
    edges: current.edges.concat(incoming.edges.filter((edge) => !edgeIds.has(edge.id))),
    positions: merged,
  };
}
