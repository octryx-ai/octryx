// Adding a node to the flow canvas: a new node of a type (or catalog item) with its contract, label and preset config.
import type { Dispatch, SetStateAction } from "react";
import type { FlowNodeCatalogItem, FlowNodeContract, FlowNodeType } from "./flowBuilderTypes";
import type { RfEdge, RfNode } from "./flowCanvasMapping";

type FlowNodeAdderArgs = {
  nodes: RfNode[];
  edges: RfEdge[];
  setNodes: Dispatch<SetStateAction<RfNode[]>>;
  setSelectedEdgeId: Dispatch<SetStateAction<string | null>>;
  onNodeSelect: (id: string | null) => void;
  syncToParent: (newNodes: RfNode[], newEdges: RfEdge[]) => void;
  nodeContracts: FlowNodeContract[];
};

export function createFlowNodeAdder({
  nodes, edges, setNodes, setSelectedEdgeId, onNodeSelect, syncToParent, nodeContracts,
}: FlowNodeAdderArgs) {
  return function addNode(
    type: FlowNodeType,
    agentId?: string,
    labelOverride?: string,
    contractOverride?: FlowNodeContract,
    defaultConfig?: Record<string, unknown>,
    catalogItem?: FlowNodeCatalogItem,
  ) {
    const id = `${type.replaceAll("_", "-")}-${crypto.randomUUID().slice(0, 8)}`;
    const contract =
      contractOverride ?? nodeContracts.find((item) => item.type === type);
    const label =
      labelOverride ?? contract?.display_name ?? type.replaceAll("_", " ");

    // Build preset config based on node type and label
    const config: Record<string, unknown> = { ...(defaultConfig ?? {}) };
    if (agentId) {
      config.agent_definition_id = agentId;
    }
    if (type === "trigger") {
      const triggerTypeMap: Record<string, string> = {
        Manual: "manual",
        Scheduler: "scheduler",
        Webhook: "webhook",
      };
      config.trigger_type = triggerTypeMap[labelOverride ?? ""] ?? "manual";
    }

    const newNode: RfNode = {
      id,
      type: "flowNode",
      position: { x: 120 + nodes.length * 300, y: 120 + (nodes.length % 2) * 96 },
      data: {
        id,
        type,
        label,
        input_schema: contract?.input_schema ?? {},
        output_schema: contract?.output_schema ?? {},
        config,
        catalog_binding: catalogItem
          ? {
              id: catalogItem.id,
              binding_type: catalogItem.binding_type,
              binding_ref: catalogItem.binding_ref,
              availability_status: catalogItem.availability_status,
            }
          : undefined,
      },
    };
    setNodes((current) => {
      const updatedNodes = [...current, newNode];
      syncToParent(updatedNodes, edges);
      return updatedNodes;
    });
    setSelectedEdgeId(null);
    onNodeSelect(id);
  };
}
