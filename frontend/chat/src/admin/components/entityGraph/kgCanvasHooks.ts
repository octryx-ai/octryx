// The knowledge graph canvas's hooks, in the order the canvas calls them: its view state and size, the fitting on a
// new layout or selection, the labels, the React Flow nodes and edges, and the keyboard. The work inside the memos is
// in kgCanvasModel.
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useReactFlow, type Viewport } from "@xyflow/react";

import type { EntityGraphEdge, EntityGraphNode } from "./entityGraphTypes";
import type { ClusterBox, Placed } from "./kgLayout";
import { neighbourhood } from "./kgView";
import {
  FIT, FIT_SMALL, clusterFlowNodes, entityFlowEdges, entityFlowNodes, entityLabels, entityObstacles, handleCanvasKey,
  relationLabels, shownClusterNames,
} from "./kgCanvasModel";

export function useCanvasView(mode: "full" | "ego", nodeCount: number, fitIds: string[] | undefined) {
  const flow = useReactFlow();
  const minimap = mode === "full" && nodeCount > 30;
  const fitNodes = useMemo(() => (fitIds?.length ? fitIds.map((id) => ({ id })) : undefined), [fitIds]);
  const fit = useMemo(() => ({ ...(minimap ? FIT : FIT_SMALL), ...(fitNodes ? { nodes: fitNodes } : {}) }), [minimap, fitNodes]);
  const focusFit = { ...fit, maxZoom: 1.25, duration: 300 };
  const wrapper = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState<Viewport>({ x: 0, y: 0, zoom: 1 });
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hoverId, setHoverId] = useState("");
  const [hoverEdgeId, setHoverEdgeId] = useState("");

  useEffect(() => {
    const element = wrapper.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setSize({ w: element.clientWidth, h: element.clientHeight }));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { flow, minimap, fit, focusFit, wrapper, view, setView, size, hoverId, setHoverId, hoverEdgeId, setHoverEdgeId };
}

type CanvasView = ReturnType<typeof useCanvasView>;

export function useCanvasFitting(
  { flow, fit, focusFit }: CanvasView,
  nodes: EntityGraphNode[],
  edges: EntityGraphEdge[],
  viewKey: string | undefined,
  selectedId: string,
) {
  // A new layout (new answer, or another neighbourhood) starts fitted; a selection keeps the view.
  const ids = useMemo(() => nodes.map((node) => node.id).join("|"), [nodes]);
  const shape = viewKey ?? ids;
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => { void flow.fitView({ ...fit, duration: 200 }); });
    return () => window.cancelAnimationFrame(frame);
    // The padding follows the mode; only a new layout refits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shape, flow]);

  const focus = useMemo(() => neighbourhood(selectedId, edges), [selectedId, edges]);
  // A selection brings its neighbourhood into view (the details panel may have narrowed the canvas meanwhile).
  useEffect(() => {
    if (!selectedId) return;
    const ids = Array.from(focus).map((id) => ({ id }));
    const timer = window.setTimeout(() => { void flow.fitView({ ...focusFit, nodes: ids }); }, 60);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, focus, flow]);
  const focusEdgeCount = useMemo(
    () => edges.filter((edge) => edge.source === selectedId || edge.target === selectedId).length, [edges, selectedId]);
  return { focus, focusEdgeCount };
}

type LabelArgs = {
  nodes: EntityGraphNode[];
  positions: Map<string, Placed>;
  clusters: ClusterBox[] | undefined;
  labelPool: Set<string> | undefined;
  selectedId: string;
  matches: Set<string>;
  focus: Set<string>;
};

export function useCanvasLabels({ nodes, positions, clusters, labelPool, selectedId, matches, focus }: LabelArgs, { view, size, hoverId }: CanvasView) {
  const zoomStep = Math.round(view.zoom * 20) / 20;
  const obstacles = useMemo(() => entityObstacles(nodes, positions), [nodes, positions]);
  const shownClusters = useMemo(() => shownClusterNames(clusters, zoomStep, obstacles), [clusters, zoomStep, obstacles]);
  const labels = useMemo(
    () => entityLabels({ nodes, positions, labelPool, selectedId, hoverId, focus, matches, zoomStep, size, view, shownClusters }),
    // The pan offset only matters once the pan ends (onMoveEnd sets it); zoomStep stands for the zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodes, positions, selectedId, hoverId, focus, matches, labelPool, shownClusters, zoomStep, size.w, size.h, view.x, view.y],
  );
  return { zoomStep, obstacles, shownClusters, labels };
}

type FlowArgs = {
  nodes: EntityGraphNode[];
  edges: EntityGraphEdge[];
  positions: Map<string, Placed>;
  slots: Map<string, number>;
  selectedId: string;
  matches: Set<string>;
  fresh: Set<string> | undefined;
  faintIds: Set<string> | undefined;
  focus: Set<string>;
  focusEdgeCount: number;
};

export function useCanvasFlow(args: FlowArgs, { hoverEdgeId }: CanvasView, placed: ReturnType<typeof useCanvasLabels>) {
  const { nodes, edges, positions, slots, selectedId, matches, fresh, faintIds, focus, focusEdgeCount } = args;
  const { zoomStep, obstacles, shownClusters, labels } = placed;
  const clusterNodes = useMemo(() => clusterFlowNodes(shownClusters), [shownClusters]);
  const flowNodes = useMemo(
    () => entityFlowNodes({ nodes, positions, slots, selectedId, focus, matches, fresh, labels }),
    [nodes, positions, slots, selectedId, focus, matches, fresh, labels],
  );

  const names = useMemo(() => new Map(nodes.map((node) => [node.id, node.display_name])), [nodes]);
  const labelled = useMemo(
    () => relationLabels({ edges, positions, selectedId, hoverEdgeId, faintIds, focusEdgeCount, zoomStep, obstacles }),
    [edges, positions, selectedId, hoverEdgeId, focusEdgeCount, zoomStep, obstacles],
  );
  const flowEdges = useMemo(
    () => entityFlowEdges({ edges, positions, selectedId, hoverEdgeId, faintIds, labelled, names }),
    [edges, positions, selectedId, hoverEdgeId, labelled, names],
  );
  return { clusterNodes, flowNodes, flowEdges };
}

type KeyArgs = { onSelect: (id: string) => void; onExpand: (id: string) => void; onClear: () => void; selectedId: string };

export function useCanvasKeys({ onSelect, onExpand, onClear, selectedId }: KeyArgs, { flow, fit }: CanvasView) {
  return useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => handleCanvasKey(event, { flow, onSelect, onExpand, onClear, selectedId, fit }),
    [flow, onSelect, onExpand, onClear, selectedId, fit],
  );
}
