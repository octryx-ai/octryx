// The one mapping between a stored flow definition and the React Flow canvas. The canvas
// writes every change back through `toFlowNode`/`toDefinitionEdge`, so these functions are
// also the editor's load path: whatever they derive (default edge ids, layout positions,
// endpoint key names) is editor-derived, everything else is authored content and must
// survive a load → sync round trip unchanged.
import type { Edge, Node } from "@xyflow/react";
import type { FlowEdgeData } from "./FlowEdgeMappingEditor";
import type { FlowDefinitionEdge, FlowDefinitionNode, FlowNodeType } from "./flowBuilderTypes";

export type RfNode = Node<
  FlowDefinitionNode & {
    selected?: boolean;
    agentName?: string;
    toolNames?: string[];
    triggerType?: string;
    runStatus?: string;
  }
>;

export type RfEdge = Edge<FlowEdgeData>;

export function layoutNodes(nodes: FlowDefinitionNode[]): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, i) => {
    positions.set(node.id, { x: 120 + i * 300, y: 120 + (i % 2 === 0 ? 0 : 96) });
  });
  return positions;
}

export function defaultEdgeId(source: string, target: string): string {
  return `${source}->${target}`;
}

export function toRfNode(
  node: FlowDefinitionNode,
  selectedId: string | null,
  positions: Map<string, { x: number; y: number }>,
  agentMap: Map<string, string>,
  toolMap: Map<string, string>,
  nodeRunStatuses: Record<string, string>,
): RfNode {
  const pos = node.position ?? positions.get(node.id) ?? { x: 0, y: 0 };
  const agentId = node.config?.agent_definition_id as string | undefined;
  const allowedTools = (node.config?.allowed_tools as string[] | undefined) ?? [];
  return {
    id: node.id,
    type: "flowNode",
    position: pos,
    data: {
      ...node,
      selected: node.id === selectedId,
      agentName: agentId ? agentMap.get(agentId) : undefined,
      toolNames: allowedTools.map((t) => toolMap.get(t) ?? t),
      triggerType: node.config?.trigger_type as string | undefined,
      runStatus: nodeRunStatuses[node.id],
    },
    selected: node.id === selectedId,
  };
}

export function toRfEdge(edge: FlowDefinitionEdge): RfEdge {
  const {
    id, from_node_id, to_node_id, source_node_id, target_node_id, source_field, target_field, condition, ...extra
  } = edge;
  const source = from_node_id ?? source_node_id ?? "";
  const target = to_node_id ?? target_node_id ?? "";
  return {
    id: id ?? defaultEdgeId(source, target),
    source,
    target,
    data: {
      sourceField: source_field,
      targetField: target_field,
      condition: typeof condition === "string" ? condition : condition ? JSON.stringify(condition) : undefined,
      conditionSource: condition,
      extra,
    },
  };
}

// Canvas-only fields are dropped; every authored node field (including keys this editor does
// not know) is kept, and the canvas position is authoritative.
export function toFlowNode(rfNode: RfNode): FlowDefinitionNode {
  const {
    selected: _,
    agentName: __,
    toolNames: ___,
    triggerType: ____,
    runStatus: _____,
    ...data
  } = rfNode.data;
  return { ...data, id: rfNode.id, type: data.type as FlowNodeType, position: rfNode.position };
}

export function storedCondition(data: FlowEdgeData): FlowDefinitionEdge["condition"] | undefined {
  if (!data.condition) return undefined;
  const source = data.conditionSource;
  const sourceText = typeof source === "string" ? source : source ? JSON.stringify(source) : undefined;
  // An unedited object condition stays an object; only an edited one becomes the typed text.
  return sourceText === data.condition ? (source as FlowDefinitionEdge["condition"]) : data.condition;
}

export function toDefinitionEdge(edge: RfEdge): FlowDefinitionEdge {
  const data = edge.data ?? {};
  const condition = storedCondition(data);
  return {
    ...(data.extra ?? {}),
    id: edge.id,
    source_node_id: edge.source,
    target_node_id: edge.target,
    ...(data.sourceField ? { source_field: data.sourceField } : {}),
    ...(data.targetField ? { target_field: data.targetField } : {}),
    ...(condition ? { condition } : {}),
  };
}
