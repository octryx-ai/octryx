// The knowledge graph canvas (React Flow): pan, zoom, fit, minimap and keyboard come from the library; the
// clustered positions (kgLayout), colours, focus and label culling (kgView, entityGraphLabels) from pure modules.
// Loaded on demand by EntityGraphCanvas, so the library is only fetched when a graph is drawn.
//
// Keyboard (on the canvas): Tab moves between entities, Enter selects, E loads the selection's neighbourhood,
// Escape clears the selection, + and − zoom, 0 fits, arrow keys pan.

import { memo, type CSSProperties } from "react";
import {
  BaseEdge, Controls, EdgeLabelRenderer, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider,
  type Edge, type EdgeProps, type Node, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { EntityGraphEdge, EntityGraphNode } from "./entityGraphTypes";
import type { ClusterBox, Placed } from "./kgLayout";
import { slotColor } from "./kgView";
import { trimmed, type KgClusterData, type KgEdgeData, type KgNodeData } from "./kgCanvasModel";
import { useCanvasFitting, useCanvasFlow, useCanvasKeys, useCanvasLabels, useCanvasView } from "./kgCanvasHooks";
import "./knowledge-graph.css";

export type CanvasProps = {
  nodes: EntityGraphNode[];
  edges: EntityGraphEdge[];
  positions: Map<string, Placed>;
  slots: Map<string, number>;
  selectedId: string;
  matches: Set<string>;
  // Changes when the view is laid out anew (not when an Expand adds to it): the canvas then fits again.
  viewKey?: string;
  // When set, only these entities (and the selection, hover, neighbours, matches) get a label: the group hubs.
  labelPool?: Set<string>;
  // Fit to these entities (the groups); others (the outer ring) may be cut at the edge.
  fitIds?: string[];
  // Entities whose idle lines are drawn faint (the loosely connected ring).
  faintIds?: Set<string>;
  // Type clusters of the layout: their names are written above them.
  clusters?: ClusterBox[];
  // Entities an Expand just added: highlighted for a moment.
  fresh?: Set<string>;
  // "full": the whole view with minimap; "ego": one entity's neighbourhood (phone), no minimap.
  mode?: "full" | "ego";
  onSelect: (id: string) => void;
  onExpand: (id: string) => void;
  onClear: () => void;
};

const KgNode = memo(function KgNode({ data }: NodeProps<Node<KgNodeData>>) {
  const c = data.size / 2;
  return <div className="kg-node" data-state={data.state} data-matched={data.matched || undefined} data-fresh={data.fresh || undefined}
    data-testid="kg-node" title={`${data.name} · ${data.type}`} style={{ width: data.size, height: data.size }}>
    <Handle type="target" position={Position.Top} className="kg-node__handle" isConnectable={false} />
    <Handle type="source" position={Position.Top} className="kg-node__handle" isConnectable={false} />
    <svg className="kg-node__svg" width={data.size} height={data.size} aria-hidden="true">
      <circle className="kg-node__dot" cx={c} cy={c} r={data.r} style={{ fill: slotColor(data.slot) }} />
      {data.label ? <text className="kg-node__label" x={c} y={c + data.r} dy="1.1em" textAnchor="middle">{data.label}</text> : null}
    </svg>
  </div>;
});

const KgEdge = memo(function KgEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<Edge<KgEdgeData>>) {
  const look = data?.look ?? "idle";
  const line = trimmed(sourceX, sourceY, targetX, targetY, data?.sourceR ?? 0, data?.targetR ?? 0);
  const strong = look === "focus" || look === "hover";
  return <>
    <BaseEdge id={id} path={`M ${line.x1} ${line.y1} L ${line.x2} ${line.y2}`} className={`kg-edge kg-edge--${look}`}
      markerEnd={strong ? "url(#kg-arrow)" : undefined} interactionWidth={12} />
    {data?.label ? <EdgeLabelRenderer>
      <div className={`kg-edge-label kg-edge-label--${look}`} title={data.title}
        style={{ transform: `translate(-50%, -50%) translate(${data.label.x}px, ${data.label.y}px) scale(calc(1 / var(--kg-zoom, 1)))` }}>
        {data.label.text}
      </div>
    </EdgeLabelRenderer> : null}
  </>;
});

// A type cluster's name above it (not interactive). In SVG, so it scales with the zoom like the entity labels.
const KgCluster = memo(function KgCluster({ data }: NodeProps<Node<KgClusterData>>) {
  return <svg className="kg-cluster" width="1" height="1" aria-hidden="true">
    <text className="kg-cluster__label" x="0" y="0" textAnchor="middle">{data.text}<tspan className="kg-cluster__count"> {data.count}</tspan></text>
  </svg>;
});

const nodeTypes = { kg: KgNode, kgCluster: KgCluster };
const edgeTypes = { kg: KgEdge };

function Canvas({ nodes, edges, positions, slots, selectedId, matches, fresh, viewKey, clusters, labelPool, fitIds, faintIds, mode = "full", onSelect, onExpand, onClear }: CanvasProps) {
  const canvas = useCanvasView(mode, nodes.length, fitIds);
  const { minimap, fit, wrapper, view, setView, setHoverId, setHoverEdgeId } = canvas;
  const { focus, focusEdgeCount } = useCanvasFitting(canvas, nodes, edges, viewKey, selectedId);
  const placed = useCanvasLabels({ nodes, positions, clusters, labelPool, selectedId, matches, focus }, canvas);
  const { clusterNodes, flowNodes, flowEdges } = useCanvasFlow(
    { nodes, edges, positions, slots, selectedId, matches, fresh, faintIds, focus, focusEdgeCount }, canvas, placed);
  const onKeyDown = useCanvasKeys({ onSelect, onExpand, onClear, selectedId }, canvas);

  return <div ref={wrapper} className={`kg-canvas kg-canvas--${mode}`} style={{ "--kg-zoom": view.zoom } as CSSProperties}
    onKeyDown={onKeyDown} role="application"
    aria-label="Knowledge graph. Tab to an entity, Enter selects it, E loads its neighbourhood, Escape clears, plus and minus zoom, 0 fits.">
    <svg className="kg-canvas__defs" aria-hidden="true" width="0" height="0">
      <defs>
        <marker id="kg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 z" className="kg-canvas__arrow" />
        </marker>
      </defs>
    </svg>
    <ReactFlow nodes={[...clusterNodes, ...flowNodes] as Node[]} edges={flowEdges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
      minZoom={0.1} maxZoom={3} fitView fitViewOptions={fit}
      nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} edgesFocusable={false}
      onlyRenderVisibleElements={nodes.length > 400} proOptions={{ hideAttribution: true }}
      onMove={(_, next) => { if (Math.abs(next.zoom - view.zoom) > 0.02) setView(next); }}
      onMoveEnd={(_, next) => setView(next)} onInit={(instance) => setView(instance.getViewport())}
      onNodeClick={(_, node) => onSelect(node.id)} onNodeDoubleClick={(_, node) => onExpand(node.id)}
      onNodeMouseEnter={(_, node) => setHoverId(node.id)} onNodeMouseLeave={() => setHoverId("")}
      onEdgeMouseEnter={(_, edge) => setHoverEdgeId(edge.id)} onEdgeMouseLeave={() => setHoverEdgeId("")}
      onPaneClick={() => { if (selectedId) onClear(); }} zoomOnDoubleClick={false}>
      <Controls fitViewOptions={fit} showInteractive={false} position="bottom-right" />
      {minimap ? <MiniMap position="top-right" pannable zoomable ariaLabel="Overview of the graph"
        nodeClassName={(node) => (node.type === "kgCluster" ? "kg-mini kg-mini--none" : `kg-mini kg-mini--${(node.data as KgNodeData).slot}`)} nodeStrokeWidth={0} /> : null}
    </ReactFlow>
  </div>;
}

export default function KnowledgeGraphCanvas(props: CanvasProps) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>;
}
