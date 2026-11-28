// Louvain groups for Workspaces whose entities carry no types; deterministic, so the same graph gives the same groups.

export type GroupNode = { id: string; display_name: string; node_type: string };
export type GroupEdge = { source: string; target: string };

export const LOOSE_GROUP = "Loosely connected";
export const SMALL_GROUPS = "Smaller groups";
export const MIN_GROUP_SIZE = 3;
export const MAX_NAMED_GROUPS = 12;

type Graph = { size: number; adj: Map<number, number>[]; self: number[] };

function buildGraph(size: number, links: [number, number, number][]): Graph {
  const adj = Array.from({ length: size }, () => new Map<number, number>());
  const self = new Array<number>(size).fill(0);
  for (const [a, b, w] of links) {
    if (a === b) { self[a] += w; continue; }
    adj[a].set(b, (adj[a].get(b) ?? 0) + w);
    adj[b].set(a, (adj[b].get(a) ?? 0) + w);
  }
  return { size, adj, self };
}

function oneLevel(graph: Graph, order: number[]): number[] {
  const strength = graph.adj.map((row, i) => {
    let total = 2 * graph.self[i];
    row.forEach((w) => { total += w; });
    return total;
  });
  const m2 = strength.reduce((sum, value) => sum + value, 0);
  const community = Array.from({ length: graph.size }, (_, i) => i);
  const total = strength.slice();
  if (!m2) return community;
  for (let pass = 0; pass < 20; pass += 1) {
    let moved = false;
    for (const i of order) {
      const own = community[i];
      const links = new Map<number, number>();
      graph.adj[i].forEach((w, j) => { links.set(community[j], (links.get(community[j]) ?? 0) + w); });
      total[own] -= strength[i];
      let best = own;
      let bestGain = (links.get(own) ?? 0) - (total[own] * strength[i]) / m2;
      const candidates = Array.from(links.keys()).sort((a, b) => a - b);
      for (const c of candidates) {
        const gain = (links.get(c) ?? 0) - (total[c] * strength[i]) / m2;
        if (gain > bestGain + 1e-12) { best = c; bestGain = gain; }
      }
      total[best] += strength[i];
      if (best !== own) { community[i] = best; moved = true; }
    }
    if (!moved) break;
  }
  return community;
}

export function louvain(nodes: { id: string }[], edges: GroupEdge[]): Map<string, number> {
  const ids = nodes.map((node) => node.id).sort();
  const index = new Map(ids.map((id, i) => [id, i]));
  let links: [number, number, number][] = [];
  for (const edge of edges) {
    const a = index.get(edge.source);
    const b = index.get(edge.target);
    if (a !== undefined && b !== undefined) links.push([a, b, 1]);
  }
  let membership = ids.map((_, i) => i);
  let size = ids.length;
  for (let level = 0; level < 10 && size > 1; level += 1) {
    const graph = buildGraph(size, links);
    const degree = graph.adj.map((row) => row.size);
    const order = Array.from({ length: size }, (_, i) => i).sort((a, b) => degree[b] - degree[a] || a - b);
    const community = oneLevel(graph, order);
    // Renumber in order of first appearance so the numbers are stable.
    const renumber = new Map<number, number>();
    for (let i = 0; i < size; i += 1) if (!renumber.has(community[i])) renumber.set(community[i], renumber.size);
    if (renumber.size === size) break;
    membership = membership.map((c) => renumber.get(community[c]) as number);
    const merged = new Map<string, number>();
    for (const [a, b, w] of links) {
      const ca = renumber.get(community[a]) as number;
      const cb = renumber.get(community[b]) as number;
      const key = ca <= cb ? `${ca},${cb}` : `${cb},${ca}`;
      merged.set(key, (merged.get(key) ?? 0) + w);
    }
    links = Array.from(merged.entries()).map(([key, w]) => {
      const [a, b] = key.split(",").map(Number);
      return [a, b, w] as [number, number, number];
    });
    size = renumber.size;
  }
  return new Map(ids.map((id, i) => [id, membership[i]]));
}

export type Group = { label: string; hubId: string; size: number };
export type Grouping = { groupOf: Map<string, string>; groups: Group[]; hubs: Set<string> };

export function structureGroups(nodes: GroupNode[], edges: GroupEdge[]): Grouping {
  const ids = new Set(nodes.map((node) => node.id));
  const inView = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target) && edge.source !== edge.target);
  const degree = new Map<string, number>();
  for (const edge of inView) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  const community = louvain(nodes, inView);
  const members = new Map<number, GroupNode[]>();
  for (const node of nodes) {
    const c = community.get(node.id) ?? -1;
    const list = members.get(c) ?? [];
    list.push(node);
    members.set(c, list);
  }
  const rank = (a: GroupNode, b: GroupNode) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0)
    || a.display_name.localeCompare(b.display_name) || a.id.localeCompare(b.id);
  const real = Array.from(members.values())
    .filter((list) => list.length >= MIN_GROUP_SIZE)
    .map((list) => list.sort(rank))
    .sort((a, b) => b.length - a.length || rank(a[0], b[0]));
  const groupOf = new Map<string, string>();
  const groups: Group[] = [];
  const hubs = new Set<string>();
  const used = new Set<string>();
  real.forEach((list, index) => {
    if (index >= MAX_NAMED_GROUPS) {
      for (const node of list) groupOf.set(node.id, SMALL_GROUPS);
      hubs.add(list[0].id);
      return;
    }
    let label = `around ${list[0].display_name || "an unnamed entity"}`;
    for (let n = 2; used.has(label); n += 1) label = `around ${list[0].display_name} (${n})`;
    used.add(label);
    groups.push({ label, hubId: list[0].id, size: list.length });
    for (const node of list) groupOf.set(node.id, label);
    hubs.add(list[0].id);
    if (list.length >= 10 && list[1]) hubs.add(list[1].id);
  });
  const small = real.slice(MAX_NAMED_GROUPS).reduce((sum, list) => sum + list.length, 0);
  if (small) groups.push({ label: SMALL_GROUPS, hubId: real[MAX_NAMED_GROUPS][0].id, size: small });
  let loose = 0;
  for (const node of nodes) if (!groupOf.has(node.id)) { groupOf.set(node.id, LOOSE_GROUP); loose += 1; }
  if (loose) groups.push({ label: LOOSE_GROUP, hubId: "", size: loose });
  return { groupOf, groups, hubs };
}

export function needsStructureGroups(nodes: { node_type: string }[]): boolean {
  return nodes.length >= 2 && new Set(nodes.map((node) => node.node_type)).size <= 1;
}

export function groupOfAdded(id: string, edges: GroupEdge[], groupOf: Map<string, string>): string {
  const counts = new Map<string, number>();
  for (const edge of edges) {
    const other = edge.source === id ? edge.target : edge.target === id ? edge.source : "";
    const group = other ? groupOf.get(other) : undefined;
    if (group && group !== LOOSE_GROUP) counts.set(group, (counts.get(group) ?? 0) + 1);
  }
  let best = LOOSE_GROUP;
  let most = 0;
  Array.from(counts.entries()).sort((a, b) => a[0].localeCompare(b[0])).forEach(([group, count]) => {
    if (count > most) { best = group; most = count; }
  });
  return best;
}

export function groupsNote(onlyType: string | undefined): string {
  const why = !onlyType || onlyType === "entity"
    ? "Entity types are not classified for this Workspace, so there is no type to colour by."
    : `All entities shown are of one type (${onlyType}).`;
  return `${why} Colours show groups of closely linked entities instead, each named after its most connected `
    + "entity; entities with few links sit on the outer ring. The legend filters by group.";
}
