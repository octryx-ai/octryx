// The steps of the phased graph's layered layout: layers by longest path, waypoints and links, the ordering sweeps
// and the column placement.
import { BOX_WIDTH, COLUMN_GAP, LANE_GAP } from "./phasedGraphTypes";
import type { drawnArrows } from "./phasedGraphBuild";

export type LayerNode = { id: string; real: boolean; side: number; index: number };
export type Arrow = ReturnType<typeof drawnArrows>[number];
export type Links = Map<string, string[]>;

// Sides: the main path (0), then the failure side's waypoints (1) and boxes (2).
const band = (node: LayerNode) => (node.side ? (node.real ? 2 : 1) : 0);
export const width = (node: LayerNode) => (node.real ? BOX_WIDTH : 0);
const gapBetween = (a: LayerNode, b: LayerNode) =>
  (width(a) + width(b)) / 2 + (a.real && b.real ? COLUMN_GAP : LANE_GAP);
const priority = (node: LayerNode) => (node.real ? (node.side === 0 ? 3 : 2) : 1);

// Layers: the longest path over the forward arrows.
export function longestPathLayers(ids: string[], forward: Arrow[]) {
  const layer = new Map<string, number>(ids.map((id) => [id, 0]));
  for (const id of ids) {
    for (const arrow of forward) {
      if (arrow.source === id) layer.set(arrow.target, Math.max(layer.get(arrow.target)!, layer.get(id)! + 1));
    }
  }
  return layer;
}

// The boxes per layer, with a waypoint in every layer an arrow passes, and the links between consecutive layers.
export function layeredNodes(ids: string[], forward: Arrow[], layer: Map<string, number>) {
  const layers: LayerNode[][] = [];
  const at = (index: number) => (layers[index] ??= []);
  const nodes = new Map<string, LayerNode>();
  const add = (node: LayerNode, index: number) => {
    nodes.set(node.id, node);
    at(index).push(node);
  };
  // The failure side: a box reached only through failures (a declined PR's retry choice).
  const sideOf = (id: string) => {
    const incoming = forward.filter((arrow) => arrow.target === id);
    return incoming.length && incoming.every((arrow) => arrow.tone === "failure") ? 1 : 0;
  };
  ids.forEach((id, index) => add({ id, real: true, side: sideOf(id), index }, layer.get(id)!));

  // Chains of waypoints: links between consecutive layers, used for ordering and placement.
  const links: Array<[string, string]> = [];
  const chains = new Map<string, string[]>();
  for (const arrow of forward) {
    const from = layer.get(arrow.source)!;
    const to = layer.get(arrow.target)!;
    const chain: string[] = [];
    for (let level = from + 1; level < to; level += 1) {
      const waypoint = `~${arrow.id}~${level}`;
      add({ id: waypoint, real: false, side: 0, index: ids.length + nodes.size }, level);
      chain.push(waypoint);
    }
    chains.set(arrow.id, chain);
    const path = [arrow.source, ...chain, arrow.target];
    for (let step = 1; step < path.length; step += 1) links.push([path[step - 1], path[step]]);
  }
  const uniqueLinks = [...new Map(links.map((link) => [`${link[0]}|${link[1]}`, link])).values()];
  const parents: Links = new Map();
  const children: Links = new Map();
  for (const [from, to] of uniqueLinks) {
    (parents.get(to) ?? parents.set(to, []).get(to)!).push(from);
    (children.get(from) ?? children.set(from, []).get(from)!).push(to);
  }
  return { layers, nodes, chains, parents, children };
}

// Ordering: the failure side on the right, barycentres of the neighbours' positions, stable on ties.
export function orderLayers(layers: LayerNode[][], parents: Links, children: Links) {
  const position = new Map<string, number>();
  const renumber = () => layers.forEach((row) => row.forEach((node, index) => position.set(node.id, index)));
  layers.forEach((row) => row.sort((a, b) => band(a) - band(b) || a.index - b.index));
  renumber();
  const sweep = (row: LayerNode[], neighbours: Links) => {
    const centre = (node: LayerNode) => {
      const around = neighbours.get(node.id) ?? [];
      if (!around.length) return position.get(node.id)!;
      return around.reduce((sum, id) => sum + position.get(id)!, 0) / around.length;
    };
    const keyed = row.map((node) => ({ node, key: centre(node), was: position.get(node.id)! }));
    keyed.sort((a, b) => band(a.node) - band(b.node) || a.key - b.key || a.was - b.was);
    keyed.forEach((item, index) => {
      row[index] = item.node;
      position.set(item.node.id, index);
    });
  };
  for (let round = 0; round < 4; round += 1) {
    for (let index = 1; index < layers.length; index += 1) sweep(layers[index], parents);
    for (let index = layers.length - 2; index >= 0; index -= 1) sweep(layers[index], children);
  }
}

// The x a node in `row` may take between its already placed neighbours, keeping the gaps.
function placedBounds(row: LayerNode[], placed: Map<number, number>, index: number) {
  let lo = -Infinity;
  for (let j = index - 1, span = 0; j >= 0; j -= 1) {
    span += gapBetween(row[j], row[j + 1]);
    if (placed.has(j)) {
      lo = placed.get(j)! + span;
      break;
    }
  }
  let hi = Infinity;
  for (let j = index + 1, span = 0; j < row.length; j += 1) {
    span += gapBetween(row[j - 1], row[j]);
    if (placed.has(j)) {
      hi = placed.get(j)! - span;
      break;
    }
  }
  return { lo, hi };
}

// Columns, top to bottom: each node wants the mean x of its parents (a box follows its real parents, so the main
// path is one straight column). The main path is placed first, then the side branches, then the waypoints; each
// stays between the already placed neighbours of its row, keeping the gaps.
export function placeColumns(layers: LayerNode[][], parents: Links, nodes: Map<string, LayerNode>) {
  const x = new Map<string, number>();
  layers.forEach((row) => {
    const placed = new Map<number, number>();
    const order = row.map((_, index) => index).sort((a, b) => priority(row[b]) - priority(row[a]) || a - b);
    for (const index of order) {
      const node = row[index];
      const { lo, hi } = placedBounds(row, placed, index);
      const around = (parents.get(node.id) ?? []).filter((id) => x.has(id));
      // A box follows its real parents; a waypoint follows the waypoint above it (a lane stays straight).
      const same = around.filter((id) => nodes.get(id)?.real === node.real);
      const chosen = same.length ? same : around;
      const wish = chosen.length ? chosen.reduce((sum, id) => sum + x.get(id)!, 0) / chosen.length
        : Number.isFinite(lo) ? lo : 0;
      placed.set(index, lo > hi ? lo : Math.min(Math.max(wish, lo), hi));
    }
    row.forEach((node, index) => {
      const minimum = index ? x.get(row[index - 1].id)! + gapBetween(row[index - 1], node) : -Infinity;
      x.set(node.id, Math.max(placed.get(index)!, minimum));
    });
  });
  return x;
}

