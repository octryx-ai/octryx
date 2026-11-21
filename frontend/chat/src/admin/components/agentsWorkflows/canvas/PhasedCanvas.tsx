// The flow chart of a workflow that runs in phases (D2b1): one box per node, coloured and
// marked by its kind, one labelled arrow per way forward. Loops and exits into an end of the error path are badges on
// their box; a click on one opens the box it leads to. A box where a person decides on the error path (the pause
// after a failed step) is drawn with thin arrows, shown while it or the box before it is selected or hovered. A
// group is a frame that folds into one box and unfolds again. Boxes and groups can be dragged; a click opens the
// box's panel. While the workflow is edited (D2b1, `edit`), boxes are dropped from the catalog, connected from their
// out port to another box, and every arrow has a handle that selects it; the editor owns selection and changes.
import { useState, type DragEvent, type ReactNode } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  useReactFlow,
  useStore,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type { NodeKind } from "./designer/types";
import { BOX_HEIGHT, BOX_WIDTH, type EdgeTone, type PhasedGraph, type Point } from "./phasedGraphTypes";
import { type GraphLayout } from "./phasedGraphLayout";
import type { ArrowData, BoxData, CanvasEditing } from "./phasedCanvasTypes";
import { PhasedArrow, PhasedBox, PhasedGroup } from "./PhasedCanvasNodes";
import { usePhasedCanvasElements } from "./usePhasedCanvasElements";
import { usePhasedCanvasFraming } from "./usePhasedCanvasFraming";

// The drag payload of a catalog entry (designer/DesignerCatalogPanel).
export const BOX_DRAG_TYPE = "application/x-octryx-designer-box";

// Lower than the flow builder's 0.2: a long workflow (40+ boxes) still fits as a whole on "Fit view".
const MIN_ZOOM = 0.1;
const nodeTypes = { phasedBox: PhasedBox, phasedGroup: PhasedGroup };
const edgeTypes = { phasedArrow: PhasedArrow };
// Loops are badges, never arrows.
const TONES: EdgeTone[] = ["success", "failure", "neutral", "loop"];

type PhasedCanvasProps = {
  graph: PhasedGraph;
  layout: GraphLayout;
  positions: Map<string, Point>;
  // Groups shown as one box.
  folded: ReadonlySet<string>;
  onFold: (groupId: string, fold: boolean) => void;
  // Boxes can be moved (a published version's layout, or a draft being edited).
  editable: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  // Where dragged boxes now stand (a dragged group moves all its boxes).
  onMove: (moves: Array<[string, Point]>) => void;
  onOpenPhase: (id: string) => void;
  toolbar: ReactNode;
  edit?: CanvasEditing;
};

export function PhasedCanvas({
  graph, layout, positions, folded, onFold, editable, selectedId, onSelect, onMove, onOpenPhase, toolbar, edit,
}: PhasedCanvasProps) {
  const { fitView, setViewport, screenToFlowPosition, setCenter, getZoom } = useReactFlow();
  const width = useStore((state) => state.width);
  const height = useStore((state) => state.height);
  const editing = Boolean(edit);
  const lr = layout.direction === "lr";
  // The box under the pointer: its thin error-path arrows show (as for the selected box).
  const [hovered, setHovered] = useState<string | null>(null);

  const { drawn, placements, nodes, onNodesChange, edges, onDragStop } = usePhasedCanvasElements({
    graph, layout, positions, folded, onFold, editable, selectedId, onSelect, onMove, onOpenPhase, edit, editing, lr, hovered,
  });
  const setReady = usePhasedCanvasFraming({
    graph, layout, positions, drawn, width, height, editing, lr, edit, view: { fitView, setViewport, setCenter, getZoom },
  });

  const onDragOver = (event: DragEvent) => {
    if (!edit || !event.dataTransfer.types.includes(BOX_DRAG_TYPE)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };
  const onDrop = (event: DragEvent) => {
    const kind = edit ? event.dataTransfer.getData(BOX_DRAG_TYPE) : "";
    if (!edit || !kind) return;
    event.preventDefault();
    const at = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    edit.onDropBox(kind as NodeKind, { x: at.x - BOX_WIDTH / 2, y: at.y - BOX_HEIGHT / 2 });
  };

  return (
    <div className="aw-pcanvas">
      <div className="aw-pcanvas__toolbar">{toolbar}</div>
      <div className="flow-canvas">
      <div className="flow-canvas__graph" data-testid={editing ? "designer-canvas" : "phased-canvas"} onDragOver={onDragOver} onDrop={onDrop}>
        <svg className="aw-pcanvas__defs" aria-hidden="true" width="0" height="0">
          <defs>
            {TONES.map((tone) => (
              <marker key={tone} id={`aw-arrowhead-${tone}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
                markerHeight="7" orient="auto-start-reverse" markerUnits="strokeWidth">
                <path d="M 0 0 L 10 5 L 0 10 z" className={`aw-parrow__head aw-parrow__head--${tone}`} />
              </marker>
            ))}
          </defs>
        </svg>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onInit={() => setReady(true)}
          onNodeDragStop={(_, node, dragged) => onDragStop(dragged.length ? dragged : [node])}
          onNodeClick={(event, node) => {
            if (node.type === "phasedGroup") return;
            // A folded group's box opens its first box.
            const id = placements.get(node.id)?.group.members[0] ?? node.id;
            if (edit) edit.onSelectNode(id, event.shiftKey || event.metaKey || event.ctrlKey);
            else onSelect(id);
          }}
          onNodeMouseEnter={(_, node) => setHovered(node.id)}
          onNodeMouseLeave={() => setHovered(null)}
          onEdgeClick={(_, item) => { if (edit) (item.data as ArrowData | undefined)?.onSelect?.(); }}
          onPaneClick={() => (edit ? edit.onClear() : onSelect(null))}
          onConnect={(connection) => {
            if (edit && connection.source && connection.target) edit.onConnect(connection.source, connection.target);
          }}
          connectionRadius={36}
          nodesDraggable={editable}
          nodesConnectable={editing}
          edgesFocusable={false}
          elementsSelectable
          deleteKeyCode={null}
          minZoom={MIN_ZOOM}
          maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border-soft)" />
          <Controls fitViewOptions={{ padding: 0.1, maxZoom: 1 }} showInteractive={false} />
          {editing ? null : <MiniMap pannable zoomable bgColor="var(--panel-elevated)" maskColor="color-mix(in srgb, var(--panel-strong) 72%, transparent)"
            maskStrokeColor="var(--accent)"
            nodeClassName={(node) => (node.type === "phasedGroup" ? "aw-pmini aw-pmini--group" : `aw-pmini aw-pmini--${(node.data as BoxData).family}`)}
            ariaLabel="Overview of the workflow" />}
        </ReactFlow>
      </div>
      </div>
    </div>
  );
}
