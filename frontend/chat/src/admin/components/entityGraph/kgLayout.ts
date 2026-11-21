// Layout of the knowledge graph canvas: deterministic, clustered by entity type, no overlaps.
//
// 1. Every entity type is one cluster. Its entities sit on a sunflower spiral around the cluster's hub (the
//    entity with the most relationships), spaced so that no two circles (plus room for a label) touch.
// 2. Clusters are discs. They are placed by a small simulation over the clusters only (a few dozen bodies, not
//    hundreds): clusters with many relationships between them are pulled together, and discs never overlap.
// 3. Inside a cluster an entity takes the free spiral slot that faces the clusters it links to, so most lines
//    between clusters leave from the side that is nearest.
//
// The same nodes and edges always give the same picture. Hiding a type in the legend does not lay out again;
// only a new answer from the server does. Cost: O(n log n) for the slots plus O(k² · steps) for k clusters.

export type LayoutNode = { id: string; node_type: string; degree: number };
export type LayoutEdge = { source: string; target: string };
export type Placed = { x: number; y: number; r: number; cluster: string; hub: boolean };
export type ClusterBox = { type: string; x: number; y: number; r: number; size: number };
export type GraphLayout = { nodes: Map<string, Placed>; clusters: ClusterBox[] };

const GOLDEN = Math.PI * (3 - Math.sqrt(5));
// Room between two circles for a one-line label below the upper one, in canvas units (1 unit = 1 px at zoom 1).
const GAP = 22;
const CLUSTER_GAP = 110;
// Spacing inside a cluster (room for a label) and between clusters. Groups without types use the airier one.
// `stretchX` widens the arrangement of the clusters (canvases are wider than tall); it only adds distance.
type Spacing = { gap: number; clusterGap: number; stretchX: number };
const NORMAL: Spacing = { gap: GAP, clusterGap: CLUSTER_GAP, stretchX: 1 };
const AIRY: Spacing = { gap: 40, clusterGap: 170, stretchX: 1.45 };
const STEPS = 240;

/** Circle radius by number of relationships: 7 for a leaf, up to 24 for a large hub. */
export function nodeRadius(degree: number): number {
  return 7 + Math.min(17, Math.sqrt(Math.max(0, degree)) * 2.6);
}

const byDegree = (a: LayoutNode, b: LayoutNode) => b.degree - a.degree || a.id.localeCompare(b.id);

function angleDiff(a: number, b: number): number {
  const d = Math.abs(a - b) % (2 * Math.PI);
  return d > Math.PI ? 2 * Math.PI - d : d;
}

type Cluster = { type: string; members: LayoutNode[]; spacing: number; hubR: number; r: number; x: number; y: number };

function makeClusters(nodes: LayoutNode[], sp: Spacing): Cluster[] {
  const groups = new Map<string, LayoutNode[]>();
  for (const node of nodes) {
    const list = groups.get(node.node_type) ?? [];
    list.push(node);
    groups.set(node.node_type, list);
  }
  return Array.from(groups.entries())
    .map(([type, members]) => {
      members.sort(byDegree);
      const hubR = nodeRadius(members[0].degree);
      const rest = members.slice(1);
      const restR = rest.length ? nodeRadius(rest[0].degree) : 0;
      // Sunflower spacing: neighbouring slots are about 1.6·c apart.
      const spacing = (2 * restR + sp.gap) / 1.6;
      const r = rest.length ? hubR + sp.gap / 2 + spacing * Math.sqrt(rest.length) + restR : hubR;
      return { type, members, spacing, hubR, r, x: 0, y: 0 };
    })
    .sort((a, b) => b.members.length - a.members.length || a.type.localeCompare(b.type));
}

function clusterWeights(clusters: Cluster[], nodes: LayoutNode[], edges: LayoutEdge[]): number[][] {
  const index = new Map(clusters.map((cluster, i) => [cluster.type, i]));
  const of = new Map(nodes.map((node) => [node.id, index.get(node.node_type) ?? -1]));
  const weights = clusters.map(() => clusters.map(() => 0));
  for (const edge of edges) {
    const a = of.get(edge.source) ?? -1;
    const b = of.get(edge.target) ?? -1;
    if (a < 0 || b < 0 || a === b) continue;
    weights[a][b] += 1;
    weights[b][a] += 1;
  }
  return weights;
}

// Start on a ring in a greedy order (each next cluster is the one most linked to the previous), then settle.
function placeClusters(clusters: Cluster[], weights: number[][], sp: Spacing): void {
  if (clusters.length === 1) return;
  const order = [0];
  const left = new Set(clusters.map((_, i) => i).slice(1));
  while (left.size) {
    const last = order[order.length - 1];
    let pick = -1;
    for (const i of Array.from(left)) if (pick < 0 || weights[last][i] > weights[last][pick]) pick = i;
    order.push(pick);
    left.delete(pick);
  }
  const total = clusters.reduce((sum, c) => sum + 2 * c.r + sp.clusterGap, 0);
  const ring = Math.max(total / (2 * Math.PI), clusters[0].r + sp.clusterGap);
  order.forEach((i, k) => {
    const angle = (k / order.length) * 2 * Math.PI;
    clusters[i].x = Math.cos(angle) * ring;
    clusters[i].y = Math.sin(angle) * ring;
  });
  const maxWeight = Math.max(1, ...weights.flat());
  for (let step = 0; step < STEPS; step += 1) {
    const cooling = 1 - step / STEPS;
    for (let i = 0; i < clusters.length; i += 1) {
      for (let j = i + 1; j < clusters.length; j += 1) {
        const a = clusters[i];
        const b = clusters[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let dist = Math.hypot(dx, dy);
        if (dist < 1e-6) { dx = 1; dy = 0; dist = 1; }
        const want = a.r + b.r + sp.clusterGap;
        // Linked clusters pull towards touching; unlinked ones only keep their distance.
        const pull = weights[i][j] ? (dist - want) * 0.08 * (0.3 + weights[i][j] / maxWeight) : 0;
        const push = dist < want ? (want - dist) * 0.5 : 0;
        const move = (pull - push) * cooling;
        const ux = dx / dist;
        const uy = dy / dist;
        const share = b.r / (a.r + b.r);
        a.x += ux * move * share;
        a.y += uy * move * share;
        b.x -= ux * move * (1 - share);
        b.y -= uy * move * (1 - share);
      }
    }
    for (const cluster of clusters) {
      cluster.x *= 1 - 0.01 * cooling;
      cluster.y *= 1 - 0.01 * cooling;
    }
  }
  // Settle any overlap that is left (exact, independent of the cooling).
  for (let pass = 0; pass < 200; pass += 1) {
    let moved = false;
    for (let i = 0; i < clusters.length; i += 1) {
      for (let j = i + 1; j < clusters.length; j += 1) {
        const a = clusters[i];
        const b = clusters[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.hypot(dx, dy) || 1;
        const want = a.r + b.r + sp.clusterGap;
        if (dist >= want - 0.01) continue;
        const half = (want - dist) / 2 + 0.01;
        a.x -= (dx / dist) * half; a.y -= (dy / dist) * half;
        b.x += (dx / dist) * half; b.y += (dy / dist) * half;
        moved = true;
      }
    }
    if (!moved) break;
  }
}

/** The clustered layout of the given entities and relationships (see the module comment). */
export function layoutGraph(
  nodes: LayoutNode[], edges: LayoutEdge[], options: { ring?: string; airy?: boolean } = {},
): GraphLayout {
  const ringNodes = options.ring ? nodes.filter((node) => node.node_type === options.ring) : [];
  const core = ringNodes.length ? nodes.filter((node) => node.node_type !== options.ring) : nodes;
  const layout = clusterLayout(core, edges, options.airy ? AIRY : NORMAL);
  return ringNodes.length ? withRing(layout, ringNodes, options.ring as string) : layout;
}

/**
 * The loosely connected entities on rings around everything else, most connected first, so they neither crowd
 * the middle nor hide between groups. The ring is one more cluster (its label sits above the ring).
 */
function withRing(layout: GraphLayout, ring: LayoutNode[], type: string): GraphLayout {
  const placed = new Map(layout.nodes);
  let cx = 0;
  let cy = 0;
  if (layout.clusters.length) {
    const weight = layout.clusters.reduce((sum, cluster) => sum + cluster.size, 0) || 1;
    cx = layout.clusters.reduce((sum, cluster) => sum + cluster.x * cluster.size, 0) / weight;
    cy = layout.clusters.reduce((sum, cluster) => sum + cluster.y * cluster.size, 0) / weight;
  }
  const extent = layout.clusters.reduce((max, cluster) => Math.max(max, Math.hypot(cluster.x - cx, cluster.y - cy) + cluster.r), 0);
  const ordered = [...ring].sort(byDegree);
  const spacing = 2 * nodeRadius(ordered[0].degree) + GAP + 26;
  // Just outside the outermost group: the ring frames the groups instead of pushing them into the middle.
  let radius = extent + (layout.clusters.length ? 56 : 0) + nodeRadius(ordered[0].degree);
  let index = 0;
  let outer = radius;
  for (let round = 0; index < ordered.length; round += 1) {
    // Spread evenly over the whole ring (the last ring holds what is left).
    const slots = Math.min(ordered.length - index, Math.max(6, Math.floor((2 * Math.PI * radius) / spacing)));
    for (let slot = 0; slot < slots && index < ordered.length; slot += 1, index += 1) {
      const angle = (slot / slots) * 2 * Math.PI - Math.PI / 2 + round * (Math.PI / slots);
      const node = ordered[index];
      placed.set(node.id, { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius, r: nodeRadius(node.degree), cluster: type, hub: false });
    }
    outer = radius;
    radius += spacing;
  }
  return { nodes: placed, clusters: layout.clusters.concat([{ type, x: cx, y: cy, r: outer + 12, size: ring.length }]) };
}

function clusterLayout(nodes: LayoutNode[], edges: LayoutEdge[], sp: Spacing = NORMAL): GraphLayout {
  const placed = new Map<string, Placed>();
  if (!nodes.length) return { nodes: placed, clusters: [] };
  const clusters = makeClusters(nodes, sp);
  placeClusters(clusters, clusterWeights(clusters, nodes, edges), sp);
  if (sp.stretchX !== 1) for (const cluster of clusters) cluster.x *= sp.stretchX;
  const clusterOf = new Map<string, Cluster>();
  for (const cluster of clusters) for (const member of cluster.members) clusterOf.set(member.id, cluster);
  // Where each entity would like to sit: towards the mean of the clusters it links to (its own cluster aside).
  const pull = new Map<string, { x: number; y: number }>();
  for (const edge of edges) {
    const a = clusterOf.get(edge.source);
    const b = clusterOf.get(edge.target);
    if (!a || !b || a === b) continue;
    for (const [id, own, other] of [[edge.source, a, b], [edge.target, b, a]] as const) {
      const vector = pull.get(id) ?? { x: 0, y: 0 };
      const dx = other.x - own.x;
      const dy = other.y - own.y;
      const length = Math.hypot(dx, dy) || 1;
      vector.x += dx / length;
      vector.y += dy / length;
      pull.set(id, vector);
    }
  }
  for (const cluster of clusters) {
    const [hub, ...rest] = cluster.members;
    placed.set(hub.id, { x: cluster.x, y: cluster.y, r: nodeRadius(hub.degree), cluster: cluster.type, hub: true });
    const offset = cluster.hubR + sp.gap / 2;
    const slots = rest.map((_, k) => {
      const radius = offset + cluster.spacing * Math.sqrt(k + 0.5);
      const angle = k * GOLDEN;
      return { x: cluster.x + Math.cos(angle) * radius, y: cluster.y + Math.sin(angle) * radius, angle, free: true };
    });
    // The most connected entities choose first, among the innermost free slots.
    const window = Math.max(6, Math.ceil(Math.sqrt(rest.length) * 2));
    let firstFree = 0;
    for (const node of rest) {
      while (firstFree < slots.length && !slots[firstFree].free) firstFree += 1;
      const vector = pull.get(node.id);
      let pick = firstFree;
      if (vector && (vector.x || vector.y)) {
        const wanted = Math.atan2(vector.y, vector.x);
        let best = Infinity;
        for (let k = firstFree, seen = 0; k < slots.length && seen < window; k += 1) {
          if (!slots[k].free) continue;
          seen += 1;
          const cost = angleDiff(slots[k].angle, wanted) + k * 0.002;
          if (cost < best) { best = cost; pick = k; }
        }
      }
      const slot = slots[pick];
      slot.free = false;
      placed.set(node.id, { x: slot.x, y: slot.y, r: nodeRadius(node.degree), cluster: cluster.type, hub: false });
    }
  }
  return {
    nodes: placed,
    clusters: clusters.map((cluster) => ({ type: cluster.type, x: cluster.x, y: cluster.y, r: cluster.r, size: cluster.members.length })),
  };
}

/**
 * A focused neighbourhood (the phone's picture of one entity): the entity in the middle, its neighbours on one
 * ring (two when there are many), ordered by type so each type forms one arc.
 */
export function egoLayout(centre: LayoutNode, neighbours: LayoutNode[]): Map<string, Placed> {
  const placed = new Map<string, Placed>();
  const centreR = nodeRadius(centre.degree);
  placed.set(centre.id, { x: 0, y: 0, r: centreR, cluster: centre.node_type, hub: true });
  const ordered = [...neighbours].sort((a, b) => a.node_type.localeCompare(b.node_type) || byDegree(a, b));
  // About 90 canvas units between neighbours on a ring leaves room for their labels.
  const perRing = 16;
  const firstRing = Math.max(centreR + 120, (Math.min(perRing, ordered.length) * 90) / (2 * Math.PI));
  ordered.forEach((node, index) => {
    const ring = Math.floor(index / perRing);
    const onRing = Math.min(perRing, ordered.length - ring * perRing);
    const angle = ((index % perRing) / onRing) * 2 * Math.PI - Math.PI / 2 + ring * (Math.PI / perRing);
    const radius = firstRing + ring * 110;
    placed.set(node.id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, r: nodeRadius(node.degree), cluster: node.node_type, hub: false });
  });
  return placed;
}
