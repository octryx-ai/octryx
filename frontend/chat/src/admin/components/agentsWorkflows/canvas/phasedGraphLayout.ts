// Phased workflow graph: the layered top-to-bottom or left-to-right layout and saved box positions.
import {
  BADGE_ROW,
  BOX_HEIGHT,
  BOX_WIDTH,
  boxHeight,
  COLUMN_GAP,
  GROUP_HEAD,
  GROUP_PAD,
  LAYER_GAP,
  type PhasedGraph,
  type Point,
} from "./phasedGraphTypes";
import { drawnArrows } from "./phasedGraphBuild";
import {
  layeredNodes, longestPathLayers, orderLayers, placeColumns, width, type LayerNode,
} from "./phasedLayoutSteps";

// --- Layout -------------------------------------------------------------------------------------------------------

// Top to bottom, or left to right (wide screens, long workflows); saved as layout.direction.
export type LayoutDirection = "tb" | "lr";
// Left to right: the gap between two columns of boxes and the height of one row.
export const LR_LAYER_GAP = 100;
export const LR_ROW = BOX_HEIGHT + 2 * BADGE_ROW + 26;

export type GraphLayout = {
  // Top-left corner of each box (a box off the path gets one too, beside the chart, so a saved layout keeps it).
  positions: Map<string, Point>;
  // The waypoints (box-centre coordinates of the layers in between) an arrow spanning several layers runs through.
  routes: Map<string, Point[]>;
  // Each box's height: a badge adds a line.
  heights: Map<string, number>;
  // How many boxes stand one after the other on the longest way (for the default direction).
  layers: number;
  direction: LayoutDirection;
};

/**
 * The direction a workflow is drawn in: its saved choice, else top to bottom. A workflow is read from where it starts,
 * at the top (a workflow is read from top to bottom), however long it is; the canvas then opens at the
 * top at a readable zoom and scrolls down. The layer count callers pass does not change the result.
 */
export function defaultDirection(saved: unknown, _layers?: number): LayoutDirection {
  if (saved === "tb" || saved === "lr") return saved;
  return "tb";
}

// Rows: each layer starts below the tallest box of the one above it; a group's frame gets its own room (its header
// above its first box, its margin below its last), so an arrow's label never sits on the header.
function layerTops(graph: PhasedGraph, layers: LayerNode[][], heights: Map<string, number>) {
  const opens = new Set(graph.groups.map((group) => group.members[0]));
  const closes = new Set(graph.groups.map((group) => group.members.at(-1)!));
  const has = (row: LayerNode[], ids: Set<string>) => row.some((node) => ids.has(node.id));
  const tops: number[] = [];
  layers.forEach((row, index) => {
    if (!index) {
      tops.push(has(row, opens) ? GROUP_HEAD : 0);
      return;
    }
    const before = layers[index - 1];
    const above = Math.max(BOX_HEIGHT, ...before.filter((node) => node.real).map((node) => heights.get(node.id)!));
    tops.push(tops[index - 1] + above + LAYER_GAP + (has(row, opens) ? GROUP_HEAD : 0) + (has(before, closes) ? GROUP_PAD : 0));
  });
  return tops;
}

// The leftmost and rightmost edge of the boxes.
function horizontalExtent(layers: LayerNode[][], x: Map<string, number>) {
  let minX = Infinity;
  let maxX = -Infinity;
  layers.forEach((row) => row.forEach((node) => {
    minX = Math.min(minX, x.get(node.id)! - width(node) / 2);
    maxX = Math.max(maxX, x.get(node.id)! + width(node) / 2);
  }));
  return { minX, maxX };
}

type Placement = {
  graph: PhasedGraph; ids: string[]; layer: Map<string, number>; layers: LayerNode[][]; x: Map<string, number>;
  tops: number[]; heights: Map<string, number>; chains: Map<string, string[]>; direction: LayoutDirection;
};

// Left to right: a layer is a column, the top-to-bottom column order becomes the row order.
function leftToRight({ ids, layer, layers, x, heights, direction }: Placement, positions: Map<string, Point>, shift: number,
  besides: PhasedGraph["boxes"]): GraphLayout {
  const pitch = BOX_WIDTH + COLUMN_GAP;
  let bottom = 0;
  ids.forEach((id) => {
    const top = Math.round(((x.get(id)! + shift - BOX_WIDTH / 2) / pitch) * LR_ROW);
    positions.set(id, { x: layer.get(id)! * (BOX_WIDTH + LR_LAYER_GAP), y: top });
    bottom = Math.max(bottom, top + (heights.get(id) ?? BOX_HEIGHT));
  });
  besides.forEach((box, index) => {
    positions.set(box.id, { x: index * (BOX_WIDTH + COLUMN_GAP), y: bottom + LAYER_GAP + GROUP_HEAD });
  });
  return { positions, routes: new Map(), heights, layers: layers.length, direction };
}

// Whole numbers, with the leftmost box at x = 0 (fitView centres it; the numbers stay comparable in tests).
function finishLayout(placement: Placement): GraphLayout {
  const { graph, ids, layer, layers, x, tops, heights, chains, direction } = placement;
  const { minX, maxX } = horizontalExtent(layers, x);
  const shift = Number.isFinite(minX) ? -minX : 0;
  const positions = new Map<string, Point>();
  ids.forEach((id) => {
    positions.set(id, { x: Math.round(x.get(id)! + shift - BOX_WIDTH / 2), y: tops[layer.get(id)!] });
  });
  // The boxes off the path stand in one column beside the chart (not drawn; a saved layout keeps them), and so do the
  // drawn boxes of the error path, where a person decides.
  const asideX = Number.isFinite(maxX) ? Math.round(maxX + shift + COLUMN_GAP) : 0;
  const besides = [...graph.boxes.filter((box) => box.aside), ...graph.boxes.filter((box) => box.offPath)];
  let besideY = 0;
  for (const box of besides) {
    positions.set(box.id, { x: asideX, y: besideY });
    besideY += (heights.get(box.id) ?? BOX_HEIGHT) + LAYER_GAP;
  }
  if (direction === "lr") return leftToRight(placement, positions, shift, besides);
  const routes = new Map<string, Point[]>();
  for (const [arrowId, chain] of chains) {
    if (!chain.length) continue;
    routes.set(arrowId, chain.map((id) => {
      const level = layers.findIndex((row) => row.some((node) => node.id === id));
      return { x: Math.round(x.get(id)! + shift), y: tops[level] + BOX_HEIGHT / 2 };
    }));
  }
  return { positions, routes, heights, layers: layers.length, direction };
}

/**
 * A deterministic layered layout, top to bottom, of the drawn boxes. Layers: longest path over the drawn arrows.
 * Arrows spanning layers get waypoints. Order: a branch reached only through failures to the right, then
 * barycentre sweeps. Columns: each node under its parents, packed. A layer is as high as its tallest box.
 */
export function layoutPhasedGraph(graph: PhasedGraph, direction: LayoutDirection = "tb"): GraphLayout {
  const ids = graph.boxes.filter((box) => !box.offPath && !box.aside).map((box) => box.id);
  const rank = new Map(ids.map((id, index) => [id, index]));
  const heights = new Map(graph.boxes.map((box) => [box.id, boxHeight(box)]));
  // Forward arrows; a non-loop edge pointing backwards in the server's order (an invalid draft) counts as a loop.
  const forward = drawnArrows(graph).filter(
    (arrow) => !arrow.aside && arrow.source !== arrow.target && rank.has(arrow.source) && rank.has(arrow.target)
      && (rank.get(arrow.source)! < rank.get(arrow.target)!),
  );
  const layer = longestPathLayers(ids, forward);
  const { layers, nodes, chains, parents, children } = layeredNodes(ids, forward, layer);
  orderLayers(layers, parents, children);
  const x = placeColumns(layers, parents, nodes);
  const tops = layerTops(graph, layers, heights);
  return finishLayout({ graph, ids, layer, layers, x, tops, heights, chains, direction });
}

// Box positions to draw: saved ones where present, the auto-layout's elsewhere.
export function mergedPositions(auto: Map<string, Point>, saved: Record<string, Point> | undefined): Map<string, Point> {
  const merged = new Map(auto);
  for (const [id, point] of Object.entries(saved ?? {})) {
    if (merged.has(id) && Number.isFinite(point?.x) && Number.isFinite(point?.y)) merged.set(id, { x: point.x, y: point.y });
  }
  return merged;
}

// The positions to save: none while every box sits where the auto-layout draws it, else all of them, so the picture
// the user arranged stays exactly as it is even if the auto-layout changes later.
export function positionsToSave(current: Map<string, Point>, auto: Map<string, Point>): Record<string, Point> {
  const moved = [...current.entries()].some(([id, point]) => {
    const home = auto.get(id);
    return !home || Math.round(home.x) !== Math.round(point.x) || Math.round(home.y) !== Math.round(point.y);
  });
  if (!moved) return {};
  const saved: Record<string, Point> = {};
  for (const [id, point] of [...current.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    saved[id] = { x: Math.round(point.x * 10) / 10, y: Math.round(point.y * 10) / 10 };
  }
  return saved;
}
