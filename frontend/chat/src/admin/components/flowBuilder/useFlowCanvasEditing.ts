// Flow canvas editing: node/edge changes, connecting, selecting, deleting, duplicating, auto-layout and adding nodes.
import { useCallback, type Dispatch, type SetStateAction } from "react";
import {
  applyEdgeChanges,
  applyNodeChanges,
  addEdge,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import type { FlowNodeContract } from "./flowBuilderTypes";
import { createFlowNodeAdder } from "./flowCanvasAddNode";
import { layoutNodes, toFlowNode, type RfEdge, type RfNode } from "./flowCanvasMapping";
import { connectionEdge, withDuplicate } from "./flowCanvasEditingModel";
import { FIT_VIEW } from "./flowCanvasView";
import type { FlowEdgeData } from "./FlowEdgeMappingEditor";

type FitView = (options: { padding: number; maxZoom: number; duration: number }) => unknown;

type FlowCanvasEditingArgs = {
  nodes: RfNode[];
  edges: RfEdge[];
  setNodes: Dispatch<SetStateAction<RfNode[]>>;
  setEdges: Dispatch<SetStateAction<RfEdge[]>>;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  setSelectedEdgeId: Dispatch<SetStateAction<string | null>>;
  connectTargetId: string;
  setConnectTargetId: Dispatch<SetStateAction<string>>;
  onNodeSelect: (id: string | null) => void;
  syncToParent: (newNodes: RfNode[], newEdges: RfEdge[]) => void;
  fitView: FitView;
  nodeContracts: FlowNodeContract[];
};

// React Flow's own node and edge changes: removed nodes take their edges and the selection with them.
function useGraphChanges({
  nodes, edges, setNodes, setEdges, selectedNodeId, selectedEdgeId, setSelectedEdgeId, onNodeSelect, syncToParent,
}: FlowCanvasEditingArgs) {
  const handleNodesChange = useCallback(
    (changes: NodeChange<RfNode>[]) => {
      setNodes((current) => {
        const updatedNodes = applyNodeChanges(changes, current) as RfNode[];
        const existingNodeIds = new Set(updatedNodes.map((node) => node.id));
        const updatedEdges = edges.filter(
          (edge) =>
            existingNodeIds.has(edge.source) && existingNodeIds.has(edge.target),
        );
        setEdges(updatedEdges);
        if (selectedNodeId && !existingNodeIds.has(selectedNodeId)) {
          onNodeSelect(null);
        }
        syncToParent(updatedNodes, updatedEdges);
        return updatedNodes;
      });
    },
    [edges, onNodeSelect, selectedNodeId, setEdges, setNodes, syncToParent],
  );

  const handleEdgesChange = useCallback(
    (changes: EdgeChange<RfEdge>[]) => {
      setEdges((current) => {
        const updatedEdges = applyEdgeChanges(changes, current);
        if (
          selectedEdgeId &&
          !updatedEdges.some((edge) => edge.id === selectedEdgeId)
        ) {
          setSelectedEdgeId(null);
        }
        syncToParent(nodes, updatedEdges);
        return updatedEdges;
      });
    },
    [nodes, selectedEdgeId, setEdges, syncToParent],
  );
  return { handleNodesChange, handleEdgesChange };
}

// Connecting by drag and selecting by click.
function useGraphPointer({ nodes, setEdges, setSelectedEdgeId, onNodeSelect, syncToParent }: FlowCanvasEditingArgs) {
  const handleConnect = useCallback(
    (params: Connection) => {
      if (!params.source || !params.target) return;
      const newEdge: RfEdge = {
        id: `${params.source}->${params.target}`,
        source: params.source,
        target: params.target,
        data: {},
      };
      setEdges((current) => {
        const updatedEdges = addEdge(newEdge, current);
        syncToParent(nodes, updatedEdges);
        return updatedEdges;
      });
    },
    [nodes, setEdges, syncToParent],
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: RfNode) => {
      setSelectedEdgeId(null);
      onNodeSelect(node.id);
    },
    [onNodeSelect],
  );

  const onEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      setSelectedEdgeId(edge.id);
      onNodeSelect(null);
    },
    [onNodeSelect],
  );

  const onPaneClick = useCallback(() => {
    setSelectedEdgeId(null);
    onNodeSelect(null);
  }, [onNodeSelect]);
  return { handleConnect, onNodeClick, onEdgeClick, onPaneClick };
}

// The selected connection: delete it or change its field mapping.
function useEdgeEditing({ nodes, setEdges, selectedEdgeId, setSelectedEdgeId, syncToParent }: FlowCanvasEditingArgs) {
  const deleteSelectedEdge = useCallback(() => {
    if (!selectedEdgeId) return;
    setEdges((current) => {
      const updatedEdges = current.filter((edge) => edge.id !== selectedEdgeId);
      syncToParent(nodes, updatedEdges);
      return updatedEdges;
    });
    setSelectedEdgeId(null);
  }, [nodes, selectedEdgeId, setEdges, syncToParent]);

  const updateSelectedEdgeData = useCallback(
    (edgeId: string, data: FlowEdgeData) => {
      setEdges((current) => {
        const updatedEdges = current.map((edge) =>
          edge.id === edgeId ? { ...edge, data } : edge,
        );
        syncToParent(nodes, updatedEdges);
        return updatedEdges;
      });
    },
    [nodes, setEdges, syncToParent],
  );
  return { deleteSelectedEdge, updateSelectedEdgeData };
}

// The selected node: delete it or connect it to the chosen target.
function useNodeEditing({
  nodes, edges, setNodes, setEdges, selectedNodeId, setSelectedEdgeId, connectTargetId, setConnectTargetId, onNodeSelect,
  syncToParent,
}: FlowCanvasEditingArgs) {
  const deleteSelectedNode = useCallback(() => {
    if (!selectedNodeId) return;
    setNodes((current) => {
      const updatedNodes = current.filter((node) => node.id !== selectedNodeId);
      const updatedEdges = edges.filter(
        (edge) =>
          edge.source !== selectedNodeId && edge.target !== selectedNodeId,
      );
      syncToParent(updatedNodes, updatedEdges);
      setEdges(updatedEdges);
      return updatedNodes;
    });
    onNodeSelect(null);
    setConnectTargetId("");
  }, [edges, onNodeSelect, selectedNodeId, setEdges, setNodes, syncToParent]);

  const connectSelectedNodeToTarget = useCallback(() => {
    if (!selectedNodeId || !connectTargetId || selectedNodeId === connectTargetId) return;
    const sourceNode = nodes.find((node) => node.id === selectedNodeId);
    const targetNode = nodes.find((node) => node.id === connectTargetId);
    if (!sourceNode || !targetNode) return;
    const edgeId = `${selectedNodeId}->${connectTargetId}`;
    if (edges.some((edge) => edge.id === edgeId)) return;
    const updatedEdges = [...edges, connectionEdge(sourceNode, targetNode, edgeId)];
    setEdges(updatedEdges);
    syncToParent(nodes, updatedEdges);
    setSelectedEdgeId(edgeId);
    onNodeSelect(null);
    setConnectTargetId("");
  }, [connectTargetId, edges, nodes, onNodeSelect, selectedNodeId, setEdges, syncToParent]);
  return { deleteSelectedNode, connectSelectedNodeToTarget };
}

// Duplicate the selected node and lay the whole graph out again.
function useGraphArrange({
  nodes, edges, setNodes, selectedNodeId, setSelectedEdgeId, onNodeSelect, syncToParent, fitView,
}: FlowCanvasEditingArgs) {
  const duplicateSelectedNode = useCallback(() => {
    if (!selectedNodeId) return;
    const source = nodes.find((node) => node.id === selectedNodeId);
    if (!source) return;
    const id = `${source.data.type.replaceAll("_", "-")}-${crypto.randomUUID().slice(0, 8)}`;
    const nextNodes = withDuplicate(nodes, source, id);
    setNodes(nextNodes);
    syncToParent(nextNodes, edges);
    setSelectedEdgeId(null);
    onNodeSelect(id);
  }, [edges, nodes, onNodeSelect, selectedNodeId, setNodes, syncToParent]);

  const autoLayout = useCallback(() => {
    const nextPositions = layoutNodes(nodes.map((node) => toFlowNode(node)));
    const updatedNodes = nodes.map((node) => ({
      ...node,
      position: nextPositions.get(node.id) ?? node.position,
    }));
    setNodes(updatedNodes);
    syncToParent(updatedNodes, edges);
    window.requestAnimationFrame(() => fitView({ ...FIT_VIEW, duration: 300 }));
  }, [edges, fitView, nodes, setNodes, syncToParent]);
  return { duplicateSelectedNode, autoLayout };
}

export function useFlowCanvasEditing(args: FlowCanvasEditingArgs) {
  const { nodes, edges, setNodes, setSelectedEdgeId, onNodeSelect, syncToParent, nodeContracts } = args;
  const changes = useGraphChanges(args);
  const pointer = useGraphPointer(args);
  const edgeEditing = useEdgeEditing(args);
  const nodeEditing = useNodeEditing(args);
  const arrange = useGraphArrange(args);

  const addNode = createFlowNodeAdder({
    nodes, edges, setNodes, setSelectedEdgeId, onNodeSelect, syncToParent, nodeContracts,
  });

  return { ...changes, ...pointer, ...edgeEditing, ...nodeEditing, ...arrange, addNode };
}
