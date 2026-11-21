// The diagram of a phase (its steps and checks), on the flow builder's canvas: the same React Flow setup, node
// component (FlowNode), auto-layout (layoutNodes), fit and zoom limits. The chain is the definition order, so the
// graph is laid out, not dragged or wired: edits go through the toolbar and the step settings.
import { useEffect, useMemo } from "react";
import { Background, BackgroundVariant, Controls, ReactFlow, useReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { FIT_VIEW, FLOW_MIN_ZOOM } from "../../flowBuilder/flowCanvasView";
import { layoutNodes, toRfEdge, toRfNode } from "../../flowBuilder/flowCanvasMapping";
import { FlowNode } from "../../flowBuilder/FlowNode";
import { canvasEdges, canvasNode, type StepsGraphNode } from "./stepsGraphModel";

const nodeTypes = { flowNode: FlowNode };
const NO_NAMES = new Map<string, string>();

type StepsCanvasProps = {
  nodes: StepsGraphNode[];
  selectedNodeId: string | null;
  onNodeSelect: (id: string | null) => void;
  toolbar: React.ReactNode;
};

export function StepsCanvas({ nodes, selectedNodeId, onNodeSelect, toolbar }: StepsCanvasProps) {
  const { fitView } = useReactFlow();
  const flowNodes = useMemo(() => nodes.map(canvasNode), [nodes]);
  const rfNodes = useMemo(() => {
    const positions = layoutNodes(flowNodes);
    return flowNodes.map((node) => toRfNode(node, selectedNodeId, positions, NO_NAMES, NO_NAMES, {}));
  }, [flowNodes, selectedNodeId]);
  const rfEdges = useMemo(() => canvasEdges(nodes).map(toRfEdge), [nodes]);

  // Fit once the chain changes length (a new or removed step); a selection or a field edit keeps the view.
  const shape = nodes.map((node) => node.id).join("|");
  useEffect(() => {
    let timer = 0;
    // After the frame and a short settle, like the flow canvas: notices above the canvas may still change its size.
    const frame = window.requestAnimationFrame(() => {
      timer = window.setTimeout(() => void fitView({ ...FIT_VIEW, duration: 250 }), 50);
    });
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [shape, fitView]);

  return (
    <div className="flow-canvas">
      <div className="flow-canvas__graph" data-testid="steps-canvas">
        <div className="flow-canvas__toolbar" aria-live="polite">{toolbar}</div>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          minZoom={FLOW_MIN_ZOOM}
          fitView
          fitViewOptions={FIT_VIEW}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesFocusable={false}
          onNodeClick={(_, node) => onNodeSelect(node.id)}
          onPaneClick={() => onNodeSelect(null)}
        >
          <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border-soft)" />
          <Controls fitViewOptions={FIT_VIEW} showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
