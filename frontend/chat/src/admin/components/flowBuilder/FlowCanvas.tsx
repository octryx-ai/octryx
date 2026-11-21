import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type {
  FlowDefinitionJson,
  FlowNodeCatalogItem,
  FlowNodeContract,
} from "./flowBuilderTypes";
import { FlowEdgeMappingEditor } from "./FlowEdgeMappingEditor";
import type { RfEdge, RfNode } from "./flowCanvasMapping";
import { FIT_VIEW, FLOW_MIN_ZOOM, MINIMAP_MIN_NODES } from "./flowCanvasView";
import "./flowConditional.css";
import { FlowCanvasBoundary } from "./FlowCanvasBoundary";
import { FlowNode } from "./FlowNode";
import { FlowPalette } from "./FlowPalette";
import type { FlowAgentOption } from "./flowPaletteModel";
import type { useFlowCanvasEditing } from "./useFlowCanvasEditing";
import { useFlowCanvasModel } from "./useFlowCanvasModel";

const nodeTypes: Record<string, React.ComponentType<any>> = {
  flowNode: FlowNode,
};

type FlowCanvasProps = {
  definition: FlowDefinitionJson;
  onChange: (def: FlowDefinitionJson) => void;
  selectedNodeId: string | null;
  onNodeSelect: (id: string | null) => void;
  agents?: FlowAgentOption[];
  tools?: Array<{ name: string }>;
  agentsLoading?: boolean;
  nodeContracts?: FlowNodeContract[];
  nodeCatalogItems?: FlowNodeCatalogItem[];
  nodeRunStatuses?: Record<string, string>;
  paletteStartCollapsed?: boolean;
};

// Stable empty defaults: a fresh object or array per render would re-derive the nodes and loop through the sync effect.
const NO_RUN_STATUSES: Readonly<Record<string, string>> = Object.freeze({});
const NO_AGENTS: FlowAgentOption[] = [];
const NO_TOOLS: Array<{ name: string }> = [];

type FlowCanvasEditing = ReturnType<typeof useFlowCanvasEditing>;

type FlowCanvasToolbarProps = {
  selectedEdge: RfEdge | null;
  selectedNodeId: string | null;
  definition: FlowDefinitionJson;
  nodes: RfNode[];
  connectTargetId: string;
  setConnectTargetId: (id: string) => void;
  editing: FlowCanvasEditing;
};

// The toolbar above the graph: the selected connection's mapping, the selected node's actions, or a hint.
function FlowCanvasToolbar({
  selectedEdge, selectedNodeId, definition, nodes, connectTargetId, setConnectTargetId, editing,
}: FlowCanvasToolbarProps) {
  return (
    <div className="flow-canvas__toolbar" aria-live="polite">
      {selectedEdge ? (
        <FlowEdgeMappingEditor
          edge={selectedEdge}
          nodes={definition.nodes}
          onUpdate={editing.updateSelectedEdgeData}
          onDelete={editing.deleteSelectedEdge}
        />
      ) : selectedNodeId ? (
        <>
          <span>Node selected: {selectedNodeId}</span>
          <FlowCanvasConnectSelect selectedNodeId={selectedNodeId} nodes={nodes} connectTargetId={connectTargetId}
            setConnectTargetId={setConnectTargetId} />
          <button
            type="button"
            onClick={editing.connectSelectedNodeToTarget}
            disabled={!connectTargetId}
          >
            Connect
          </button>
          <button type="button" onClick={editing.duplicateSelectedNode}>
            Duplicate
          </button>
          <button type="button" onClick={editing.deleteSelectedNode}>
            Delete
          </button>
          <button type="button" onClick={editing.autoLayout}>
            Auto-layout
          </button>
        </>
      ) : (
        <>
          <span>Select a connection or node to edit the graph.</span>
          <button type="button" onClick={editing.autoLayout}>
            Auto-layout
          </button>
        </>
      )}
    </div>
  );
}

// The target a selected node can be connected to: every other node.
function FlowCanvasConnectSelect({
  selectedNodeId, nodes, connectTargetId, setConnectTargetId,
}: Pick<FlowCanvasToolbarProps, "nodes" | "connectTargetId" | "setConnectTargetId"> & { selectedNodeId: string }) {
  return (
    <select
      className="flow-canvas__connect-select"
      value={connectTargetId}
      onChange={(event) => setConnectTargetId(event.target.value)}
      aria-label="Connection target"
    >
      <option value="">Connect to...</option>
      {nodes
        .filter((node) => node.id !== selectedNodeId)
        .map((node) => (
          <option key={node.id} value={node.id}>
            {node.data.label ?? node.id}
          </option>
        ))}
    </select>
  );
}

// The React Flow graph with its background, controls and (for larger graphs) the minimap.
function FlowCanvasGraph({ nodes, displayEdges, editing }: { nodes: RfNode[]; displayEdges: RfEdge[]; editing: FlowCanvasEditing }) {
  return (
    <ReactFlow
      nodes={nodes}
      edges={displayEdges}
      onNodesChange={editing.handleNodesChange}
      onEdgesChange={editing.handleEdgesChange}
      onConnect={editing.handleConnect}
      onNodeClick={editing.onNodeClick}
      onEdgeClick={editing.onEdgeClick}
      onPaneClick={editing.onPaneClick}
      nodeTypes={nodeTypes}
      minZoom={FLOW_MIN_ZOOM}
      edgesFocusable
      elementsSelectable
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={20}
        size={1}
        color="rgba(148,163,184,0.2)"
      />
      <Controls fitViewOptions={FIT_VIEW} />
      {nodes.length >= MINIMAP_MIN_NODES ? (
        <MiniMap
          nodeColor={() => "rgba(125, 211, 252, 0.35)"}
          maskColor="rgba(15, 23, 42, 0.7)"
        />
      ) : null}
    </ReactFlow>
  );
}

function FlowCanvasInner({
  definition,
  onChange,
  selectedNodeId,
  onNodeSelect,
  agents = NO_AGENTS,
  tools = NO_TOOLS,
  agentsLoading = false,
  nodeContracts = [],
  nodeCatalogItems = [],
  nodeRunStatuses = NO_RUN_STATUSES,
  paletteStartCollapsed = false,
}: FlowCanvasProps) {
  const {
    nodes, selectedEdge, displayEdges, connectTargetId, setConnectTargetId, graphRef, onPaletteCollapsedChange, editing,
  } = useFlowCanvasModel({ definition, onChange, selectedNodeId, onNodeSelect, agents, tools, nodeContracts, nodeRunStatuses });

  return (
    <div className="flow-canvas">
      <FlowPalette
        onAddNode={editing.addNode}
        agents={agents}
        nodeContracts={nodeContracts}
        nodeCatalogItems={nodeCatalogItems}
        loading={agentsLoading}
        isCollapsed={paletteStartCollapsed}
        onCollapsedChange={onPaletteCollapsedChange}
      />
      <div className="flow-canvas__graph" ref={graphRef}>
        <FlowCanvasToolbar selectedEdge={selectedEdge} selectedNodeId={selectedNodeId} definition={definition} nodes={nodes}
          connectTargetId={connectTargetId} setConnectTargetId={setConnectTargetId} editing={editing} />
        <FlowCanvasGraph nodes={nodes} displayEdges={displayEdges} editing={editing} />
      </div>
    </div>
  );
}

export function FlowCanvas(props: FlowCanvasProps) {
  return (
    <FlowCanvasBoundary>
      <FlowCanvasInner {...props} />
    </FlowCanvasBoundary>
  );
}
