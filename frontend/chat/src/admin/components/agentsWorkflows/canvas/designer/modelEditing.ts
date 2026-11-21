// Designer model editing: add, change, move and remove boxes, and draw, move or route the arrows between them.
import { exitValues } from "./inspector/exitValues";
import { kindName } from "./inspector/labels";
import { defaultConfig } from "./inspector/nodeDefaults";
import type { DefEdge, DefNode, DesignerCatalog, EdgePatch, NodeKind, NodePatch } from "./types";
import {
  clone, DEFAULT_LOOP_LIMIT, edgeIds, findEdge, findNode, ID_STEMS, isBackEdge, nodeIds, uniqueId, withoutMembers,
  type DesignModel, type Point,
} from "./modelCore";

// --- Boxes -------------------------------------------------------------------------------------------------------

/** ``drawn``: where the canvas shows each box now (hand-set or automatic) and its direction, so an End the user never
 *  moved is kept after the new box (below it top to bottom, right of it left to right). */
export type DrawnLayout = { positions: ReadonlyMap<string, Point>; direction: "tb" | "lr" };

export function addNode(model: DesignModel, type: NodeKind, at?: Point, drawn?: DrawnLayout): { model: DesignModel; id: string } {
  const id = uniqueId(ID_STEMS[type] ?? type.replace(/_/g, "-"), nodeIds(model));
  const node: DefNode = { id, type, label: type === "outcome" ? "Done" : kindName(type), config: defaultConfig(type) };
  const positions = at ? { ...model.positions, [id]: { x: Math.round(at.x), y: Math.round(at.y) } } : model.positions;
  return { id, model: keepEndsLast({ ...model, nodes: [...model.nodes, node], positions }, type === "outcome" ? id : null, drawn) };
}

const END_GAP_LR = 280;
const END_GAP_TB = 140;

/** An End box the user never moved (no hand-set position, or one the designer set) stays right of every other box,
 *  so a new step never lands behind the End ("Done" sat between Start and Triage). */
function keepEndsLast(model: DesignModel, added: string | null, drawn?: DrawnLayout): DesignModel {
  const auto = new Set(model.autoEnds ?? []);
  const ends = model.nodes.filter((node) => node.type === "outcome" && node.id !== added
    && (auto.has(node.id) || !model.positions[node.id])).map((node) => node.id);
  const shown = new Map<string, Point>(drawn?.positions ?? []);
  for (const [id, point] of Object.entries(model.positions)) shown.set(id, point);
  const others = [...shown.entries()].filter(([id]) => !ends.includes(id) && model.nodes.some((node) => node.id === id));
  if (!ends.length || !others.length) return model;
  const positions = { ...model.positions };
  if (drawn?.direction === "tb") {
    const below = Math.max(...others.map(([, point]) => point.y)) + END_GAP_TB;
    const column = Math.min(...others.map(([, point]) => point.x));
    ends.forEach((id, index) => { positions[id] = { x: column + index * 240, y: below }; });
  } else {
    const right = Math.max(...others.map(([, point]) => point.x)) + END_GAP_LR;
    const rows = others.map(([, point]) => point.y);
    const middle = Math.round((Math.min(...rows) + Math.max(...rows)) / 2);
    ends.forEach((id, index) => { positions[id] = { x: right, y: middle + index * 120 }; });
  }
  return { ...model, positions, autoEnds: ends };
}

export function updateNode(model: DesignModel, id: string, patch: NodePatch): DesignModel {
  return {
    ...model,
    nodes: model.nodes.map((node) => (node.id === id ? {
      ...node,
      ...(patch.label !== undefined ? { label: patch.label } : {}),
      ...(patch.config !== undefined ? { config: clone(patch.config) } : {}),
    } : node)),
  };
}

export function moveNodes(model: DesignModel, moves: Array<[string, Point]>): DesignModel {
  const positions = { ...model.positions };
  for (const [id, point] of moves) positions[id] = { x: Math.round(point.x), y: Math.round(point.y) };
  const moved = new Set(moves.map(([id]) => id));
  return { ...model, positions, autoEnds: (model.autoEnds ?? []).filter((id) => !moved.has(id)) };
}

/** Every box at this position (the automatic layout's, so nothing jumps when the structure changes). */
export function setPositions(model: DesignModel, positions: Map<string, Point> | Record<string, Point>): DesignModel {
  const entries = positions instanceof Map ? [...positions] : Object.entries(positions);
  const known = new Set(nodeIds(model));
  return { ...model, positions: Object.fromEntries(entries.filter(([id]) => known.has(id)).map(([id, point]) => [id, { x: Math.round(point.x), y: Math.round(point.y) }])) };
}

/** The start is the one entry: it can be neither removed nor copied. */
export const removable = (node: DefNode | undefined) => Boolean(node && node.type !== "start");


/** Removes the boxes (with every arrow at them) and the arrows. */
export function removeItems(model: DesignModel, nodes: string[], edges: string[] = []): DesignModel {
  const gone = new Set(nodes.filter((id) => removable(findNode(model, id))));
  const goneEdges = new Set(edges);
  if (!gone.size && !goneEdges.size) return model;
  const positions = Object.fromEntries(Object.entries(model.positions).filter(([id]) => !gone.has(id)));
  return {
    ...model,
    nodes: model.nodes.filter((node) => !gone.has(node.id)),
    edges: model.edges.filter((edge) => !goneEdges.has(edge.id) && !gone.has(edge.source) && !gone.has(edge.target)),
    positions,
    groups: withoutMembers(model.groups, gone),
  };
}

// --- Arrows ------------------------------------------------------------------------------------------------------

export type ConnectResult = { model: DesignModel; edgeId: string | null; problem?: string };

function kindFor(model: DesignModel, source: string, target: string, keep?: DefEdge): Pick<DefEdge, "kind" | "max_iterations"> {
  if (isBackEdge(model, source, target)) {
    return { kind: "loop", max_iterations: keep?.kind === "loop" && keep.max_iterations ? keep.max_iterations : DEFAULT_LOOP_LIMIT };
  }
  return { kind: "next", max_iterations: null };
}

/**
 * An arrow from ``source`` to ``target``, taken for ``when``. A box with one way out keeps one arrow: a new one moves
 * it. A box with several results takes ``when`` (none yet: its panel asks); an arrow already taken for it is moved. An arrow to a box before
 * the source (or to the source itself) is a way back with a maximum; any other one is a way on.
 */
export function connect(model: DesignModel, source: string, target: string, when: string | null, catalog: DesignerCatalog): ConnectResult {
  const from = findNode(model, source);
  const to = findNode(model, target);
  if (!from || !to) return { model, edgeId: null, problem: "Both boxes must exist." };
  if (from.type === "outcome") return { model, edgeId: null, problem: "An end has no way out." };
  if (to.type === "start") return { model, edgeId: null, problem: "Nothing leads back to the start." };
  const choices = exitValues(from, catalog);
  if (choices === null) {
    const existing = model.edges.find((edge) => edge.source === source);
    if (existing) return { model: retarget(model, existing.id, target), edgeId: existing.id };
    when = null;
  } else {
    // Without a result the arrow is drawn all the same; its panel asks for which result it is taken.
    const existing = model.edges.find((edge) => edge.source === source && edge.when === (when || null));
    if (existing) return { model: retarget(model, existing.id, target), edgeId: existing.id };
    when = when || null;
  }
  const id = uniqueId(`e-${source}`, edgeIds(model));
  const edge: DefEdge = { id, source, target, when, ...kindFor(model, source, target) };
  return { model: { ...model, edges: [...model.edges, edge] }, edgeId: id };
}

/** The arrow now ends at ``target``; whether it goes on or back follows from where the target is. */
export function retarget(model: DesignModel, edgeId: string, target: string): DesignModel {
  const edge = findEdge(model, edgeId);
  if (!edge || !findNode(model, target)) return model;
  const others = { ...model, edges: model.edges.filter((item) => item.id !== edgeId) };
  const next: DefEdge = { ...edge, target, ...kindFor(others, edge.source, target, edge) };
  return { ...model, edges: model.edges.map((item) => (item.id === edgeId ? next : item)) };
}

export function updateEdge(model: DesignModel, edgeId: string, patch: EdgePatch): DesignModel {
  return {
    ...model,
    edges: model.edges.map((edge) => {
      if (edge.id !== edgeId) return edge;
      const next: DefEdge = { ...edge, ...patch };
      if ("label" in patch && patch.label === undefined) delete next.label;
      return next;
    }),
  };
}

/**
 * The side panel's ``onRoute(when, target)`` (Decisions S3): the arrow of ``source`` for ``when`` is created, moved
 * or (``target`` null) removed.
 */
export function route(model: DesignModel, source: string, when: string, target: string | null): DesignModel {
  const existing = model.edges.find((edge) => edge.source === source && edge.when === when);
  if (target === null) return existing ? removeItems(model, [], [existing.id]) : model;
  if (existing) return retarget(model, existing.id, target);
  const from = findNode(model, source);
  if (!from || !findNode(model, target) || from.type === "outcome") return model;
  const id = uniqueId(`e-${source}`, edgeIds(model));
  return { ...model, edges: [...model.edges, { id, source, target, when, ...kindFor(model, source, target) }] };
}

