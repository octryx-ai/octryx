// The flow canvas's state: React Flow nodes and edges derived from the definition, the edge and connect selection,
// the display-only branch labels, the write back to the definition, viewport fitting and the editing handlers.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useEdgesState, useNodesState, useReactFlow } from "@xyflow/react";
import type { FlowDefinitionJson, FlowNodeContract } from "./flowBuilderTypes";
import { layoutNodes, storedCondition, toDefinitionEdge, toFlowNode, toRfEdge, toRfNode, type RfEdge, type RfNode } from "./flowCanvasMapping";
import { branchEdgeLabels, withBranchLabels } from "./flowEdgeBranchLabels";
import type { FlowAgentOption } from "./flowPaletteModel";
import { useFlowCanvasEditing } from "./useFlowCanvasEditing";
import { useFlowCanvasFit } from "./useFlowCanvasFit";

export type FlowCanvasModelArgs = {
  definition: FlowDefinitionJson;
  onChange: (def: FlowDefinitionJson) => void;
  selectedNodeId: string | null;
  onNodeSelect: (id: string | null) => void;
  agents: FlowAgentOption[];
  tools: Array<{ name: string }>;
  nodeContracts: FlowNodeContract[];
  nodeRunStatuses: Record<string, string>;
};

// React Flow's nodes and edges for the definition, kept as editable state.
function useFlowCanvasElements({ definition, selectedNodeId, agents, tools, nodeRunStatuses }: FlowCanvasModelArgs) {
  const agentMap = useMemo(
    () => new Map(agents.map((a) => [a.id, a.name])),
    [agents],
  );
  const toolMap = useMemo(
    () => new Map(tools.map((t) => [t.name, t.name])),
    [tools],
  );

  const positions = useMemo(
    () => layoutNodes(definition.nodes),
    [definition.nodes],
  );

  const rfNodes = useMemo(
    () =>
      definition.nodes.map((n) =>
        toRfNode(n, selectedNodeId, positions, agentMap, toolMap, nodeRunStatuses),
      ),
    [definition.nodes, selectedNodeId, positions, agentMap, toolMap, nodeRunStatuses],
  );

  const rfEdges = useMemo(
    () => definition.edges.map(toRfEdge),
    [definition.edges],
  );

  const [nodes, setNodes] = useNodesState(rfNodes);
  const [edges, setEdges] = useEdgesState(rfEdges);
  return { rfNodes, rfEdges, nodes, setNodes, edges, setEdges };
}

// The selected edge, the branch labels shown on it and its siblings, and the write back to the definition.
function useFlowCanvasSync(
  { definition, onChange }: FlowCanvasModelArgs,
  { rfNodes, rfEdges, nodes, setNodes, edges, setEdges }: ReturnType<typeof useFlowCanvasElements>,
) {
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [connectTargetId, setConnectTargetId] = useState("");

  const selectedEdge = useMemo(
    () => edges.find((edge) => edge.id === selectedEdgeId) ?? null,
    [edges, selectedEdgeId],
  );

  // Display-only branch labels on the connections out of If / else steps: derived from
  // the current rules and conditions on every change, passed to React Flow only, never stored.
  const displayEdges = useMemo(() => {
    const labels = branchEdgeLabels(
      nodes.map((node) => node.data),
      edges.map((edge) => ({ id: edge.id, source: edge.source, condition: storedCondition(edge.data ?? {}) })),
    );
    return withBranchLabels(edges, labels);
  }, [nodes, edges]);

  const syncToParent = useCallback(
    (newNodes: RfNode[], newEdges: RfEdge[]) => {
      onChange({
        ...definition,
        nodes: newNodes.map(toFlowNode),
        edges: newEdges.filter((e) => e.source && e.target).map(toDefinitionEdge),
      });
    },
    [definition, onChange],
  );

  // Sync nodes/edges when definition changes externally.
  useEffect(() => {
    setNodes(rfNodes);
    setEdges(rfEdges);
  }, [rfNodes, rfEdges, setNodes, setEdges]);
  return { selectedEdgeId, setSelectedEdgeId, connectTargetId, setConnectTargetId, selectedEdge, displayEdges, syncToParent };
}

export function useFlowCanvasModel(args: FlowCanvasModelArgs) {
  const { definition, selectedNodeId, onNodeSelect, nodeContracts } = args;
  const { fitView } = useReactFlow();
  // Guard fitView calls to avoid calling before React Flow is fully initialized
  const initialized = useRef(false);

  // Mark initialized once after mount
  useEffect(() => {
    initialized.current = true;
  }, []);

  const elements = useFlowCanvasElements(args);
  const { nodes, setNodes, edges, setEdges } = elements;
  const sync = useFlowCanvasSync(args, elements);
  const { selectedEdgeId, setSelectedEdgeId, connectTargetId, setConnectTargetId, syncToParent } = sync;

  const { graphRef, onPaletteCollapsedChange } = useFlowCanvasFit({
    fitView,
    initialized,
    definition,
    selectedNodeId,
    nodes,
  });

  const editing = useFlowCanvasEditing({
    nodes, edges, setNodes, setEdges, selectedNodeId, selectedEdgeId, setSelectedEdgeId, connectTargetId,
    setConnectTargetId, onNodeSelect, syncToParent, fitView, nodeContracts,
  });
  return { nodes, ...sync, graphRef, onPaletteCollapsedChange, editing };
}
