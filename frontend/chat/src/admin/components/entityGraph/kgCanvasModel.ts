// The knowledge graph canvas's pure parts: node and edge data for React Flow, label and cluster-name placement, and
// what a key on the canvas does. No React: the canvas hooks call these inside their memos and callbacks.
import type { Edge, Node, ReactFlowInstance, Viewport } from "@xyflow/react";
import type { KeyboardEvent } from "react";

import type { EntityGraphEdge, EntityGraphNode } from "./entityGraphTypes";
import type { ClusterBox, Placed } from "./kgLayout";
import {
  edgeLabels, edgeLook, labelOrder, placeClusterLabels, placeEdgeLabels, showsEdgeLabel, type EdgeLook, type LabelObstacle,
  type PlacedEdgeLabel,
} from "./kgView";
import { placeLabels } from "./entityGraphLabels";
import { humanizeRelation } from "./entityGraphDetailModel";

export type NodeState = "selected" | "linked" | "dim" | "idle";
export type KgNodeData = {
  name: string; type: string; slot: number; r: number; size: number; state: NodeState; matched: boolean; fresh: boolean; label: string;
};
export type KgEdgeData = { look: EdgeLook; label: PlacedEdgeLabel | null; title: string; sourceR: number; targetR: number };
export type KgClusterData = { text: string; count: number };

const LABEL_PX = 12;
const MIN_HIT = 24;
// The minimap (top right, 192 px + margins) and the zoom controls (bottom right) own a column on the right: a fitted
// graph never lies under them. The legend sits below the canvas, so the bottom needs no extra room.
export const FIT = { padding: { top: "24px", left: "24px", right: "224px", bottom: "24px" }, maxZoom: 1.4 } as const;
// Without a minimap (phone neighbourhood, small graphs) only the controls need room.
export const FIT_SMALL = { padding: { top: "24px", left: "24px", right: "64px", bottom: "24px" }, maxZoom: 1.4 } as const;

// A straight line from circle edge to circle edge (not centre to centre), so the arrow head stays visible.
export function trimmed(sx: number, sy: number, tx: number, ty: number, sr: number, tr: number) {
  const dx = tx - sx;
  const dy = ty - sy;
  const length = Math.hypot(dx, dy) || 1;
  const ux = dx / length;
  const uy = dy / length;
  return { x1: sx + ux * sr, y1: sy + uy * sr, x2: tx - ux * (tr + 2), y2: ty - uy * (tr + 2) };
}

// Circles a relationship label must keep clear of: every drawn entity.
export function entityObstacles(nodes: EntityGraphNode[], positions: Map<string, Placed>): LabelObstacle[] {
  return nodes.flatMap((node) => {
    const at = positions.get(node.id);
    return at ? [{ x: at.x, y: at.y, r: at.r }] : [];
  });
}

// Cluster names that fit at this zoom (the largest first; never over another name or an entity).
export function shownClusterNames(clusters: ClusterBox[] | undefined, zoomStep: number, obstacles: LabelObstacle[]) {
  const spots = (clusters ?? []).filter((cluster) => cluster.size > 1)
    .map((cluster) => ({ ...cluster, text: `${cluster.type} ${cluster.size}` }));
  const fits = placeClusterLabels(spots, zoomStep, obstacles);
  return { spots: spots.filter((spot) => fits.has(spot.type)), boxes: Array.from(fits.values()) };
}

export type ShownClusters = ReturnType<typeof shownClusterNames>;

type LabelInput = {
  nodes: EntityGraphNode[];
  positions: Map<string, Placed>;
  labelPool: Set<string> | undefined;
  selectedId: string;
  hoverId: string;
  focus: Set<string>;
  matches: Set<string>;
  zoomStep: number;
  size: { w: number; h: number };
  view: Viewport;
  shownClusters: ShownClusters;
};

// Labels: by priority, skipping any that would collide at the current zoom or lie outside the visible part.
export function entityLabels(input: LabelInput) {
  const { nodes, positions, labelPool, selectedId, hoverId, focus, matches, zoomStep, size, view } = input;
  const candidates = nodes.flatMap((node) => {
    const at = positions.get(node.id);
    if (labelPool && !labelPool.has(node.id) && node.id !== selectedId && node.id !== hoverId && !focus.has(node.id)
      && !matches.has(node.id)) return [];
    return at ? [{ id: node.id, x: at.x, y: at.y, radius: at.r, display_name: node.display_name, degree: node.degree, hub: at.hub, name: node.display_name }] : [];
  });
  const order = labelOrder(candidates, { selectedId, hoverId, neighbours: focus, matches });
  const zoom = zoomStep || 1;
  const visible = size.w ? { x: -view.x / zoom, y: -view.y / zoom, w: size.w / zoom, h: size.h / zoom } : undefined;
  // Group names win: an entity label that would touch one gives way.
  return placeLabels(candidates, order, LABEL_PX / zoom, visible, input.shownClusters.boxes);
}

export function clusterFlowNodes(shownClusters: ShownClusters): Node<KgClusterData>[] {
  return shownClusters.spots.map((cluster) => ({
    id: `cluster:${cluster.type}`, type: "kgCluster", position: { x: cluster.x, y: cluster.y - cluster.r - 18 },
    width: 1, height: 1, selectable: false, focusable: false, draggable: false, connectable: false, zIndex: -1,
    className: "kg-cluster-node", data: { text: cluster.type, count: cluster.size },
  }));
}

type FlowNodeInput = {
  nodes: EntityGraphNode[];
  positions: Map<string, Placed>;
  slots: Map<string, number>;
  selectedId: string;
  focus: Set<string>;
  matches: Set<string>;
  fresh: Set<string> | undefined;
  labels: ReturnType<typeof entityLabels>;
};

export function entityFlowNodes({ nodes, positions, slots, selectedId, focus, matches, fresh, labels }: FlowNodeInput): Node<KgNodeData>[] {
  return nodes.flatMap((node) => {
    const at = positions.get(node.id);
    if (!at) return [];
    const size = Math.max(MIN_HIT, at.r * 2);
    const state: NodeState = !selectedId ? "idle" : node.id === selectedId ? "selected" : focus.has(node.id) ? "linked" : "dim";
    return [{
      id: node.id, type: "kg", position: { x: at.x - size / 2, y: at.y - size / 2 }, width: size, height: size,
      selected: node.id === selectedId, draggable: false, connectable: false,
      ariaLabel: `${node.display_name}, ${node.node_type}, ${node.degree} ${node.degree === 1 ? "relationship" : "relationships"}`,
      data: { name: node.display_name, type: node.node_type, slot: slots.get(node.node_type) ?? 0, r: at.r, size, state,
        matched: matches.has(node.id), fresh: Boolean(fresh?.has(node.id)), label: labels.get(node.id)?.text ?? "" },
    }];
  });
}

type EdgeLabelInput = {
  edges: EntityGraphEdge[];
  positions: Map<string, Placed>;
  selectedId: string;
  hoverEdgeId: string;
  faintIds: Set<string> | undefined;
  focusEdgeCount: number;
  zoomStep: number;
  obstacles: LabelObstacle[];
};

export function relationLabels({ edges, positions, selectedId, hoverEdgeId, faintIds, focusEdgeCount, zoomStep, obstacles }: EdgeLabelInput) {
  const texts = edgeLabels(edges.map((edge) => ({
    id: edge.id, source: edge.source, target: edge.target, relation: humanizeRelation(edge.edge_type),
    labelled: showsEdgeLabel(edgeLook(edge, selectedId, hoverEdgeId, faintIds), focusEdgeCount),
  })));
  // The hovered relationship claims its spot first.
  const ordered = [...edges].sort((a, b) => Number(b.id === hoverEdgeId) - Number(a.id === hoverEdgeId));
  return placeEdgeLabels(ordered.flatMap((edge) => {
    const text = texts.get(edge.id);
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!text || !source || !target) return [];
    return [{ id: edge.id, text, ...trimmed(source.x, source.y, target.x, target.y, source.r, target.r) }];
  }), zoomStep, obstacles);
}

type FlowEdgeInput = Pick<EdgeLabelInput, "edges" | "positions" | "selectedId" | "hoverEdgeId" | "faintIds"> & {
  labelled: ReturnType<typeof relationLabels>;
  names: Map<string, string>;
};

export function entityFlowEdges({ edges, positions, selectedId, hoverEdgeId, faintIds, labelled, names }: FlowEdgeInput): Edge<KgEdgeData>[] {
  return edges.flatMap((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target || edge.source === edge.target) return [];
    const look = edgeLook(edge, selectedId, hoverEdgeId, faintIds);
    const relation = humanizeRelation(edge.edge_type);
    return [{
      id: edge.id, source: edge.source, target: edge.target, type: "kg", selectable: false, focusable: false,
      zIndex: look === "focus" || look === "hover" ? 1 : 0,
      data: { look, label: labelled.get(edge.id) ?? null, sourceR: source.r, targetR: target.r,
        title: `${names.get(edge.source) ?? ""} → ${relation} → ${names.get(edge.target) ?? ""}` },
    }];
  });
}

type KeyContext = {
  flow: ReactFlowInstance;
  onSelect: (id: string) => void;
  onExpand: (id: string) => void;
  onClear: () => void;
  selectedId: string;
  fit: object;
};

const PAN: Record<string, [number, number]> = { ArrowLeft: [80, 0], ArrowRight: [-80, 0], ArrowUp: [0, 80], ArrowDown: [0, -80] };

export function handleCanvasKey(event: KeyboardEvent<HTMLDivElement>, { flow, onSelect, onExpand, onClear, selectedId, fit }: KeyContext) {
  const target = event.target as HTMLElement;
  const nodeId = target.closest?.(".react-flow__node")?.getAttribute("data-id") ?? "";
  if (event.key === "Enter" && nodeId) { event.preventDefault(); onSelect(nodeId); return; }
  if ((event.key === "e" || event.key === "E") && (nodeId || selectedId)) { event.preventDefault(); onExpand(nodeId || selectedId); return; }
  if (event.key === "Escape" && selectedId) { event.preventDefault(); onClear(); return; }
  if (event.key === "+" || event.key === "=") { event.preventDefault(); void flow.zoomIn({ duration: 150 }); return; }
  if (event.key === "-") { event.preventDefault(); void flow.zoomOut({ duration: 150 }); return; }
  if (event.key === "0") { event.preventDefault(); void flow.fitView({ ...fit, duration: 200 }); return; }
  if (PAN[event.key] && !nodeId) {
    event.preventDefault();
    const current = flow.getViewport();
    void flow.setViewport({ ...current, x: current.x + PAN[event.key][0], y: current.y + PAN[event.key][1] }, { duration: 120 });
  }
}
