// A phase's graph nodes and edges as React Flow canvas elements, laid out left to right.
import type { Edge, Node } from "@xyflow/react";
import type { FlowDefinitionEdge, FlowDefinitionNode } from "./flowBuilderTypes";

export type RfNode = Node<FlowDefinitionNode & { selected?: boolean }>;

export function layoutNodes(nodes: FlowDefinitionNode[]): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, i) => {
    positions.set(node.id, { x: 120 + i * 300, y: 120 + (i % 2 === 0 ? 0 : 96) });
  });
  return positions;
}

export function toRfNode(
  node: FlowDefinitionNode,
  selectedId: string | null,
  positions: Map<string, { x: number; y: number }>,
): RfNode {
  const position = positions.get(node.id) ?? { x: 0, y: 0 };
  const selected = node.id === selectedId;
  return { id: node.id, type: "flowNode", position, data: { ...node, selected }, selected };
}

export function toRfEdge(edge: FlowDefinitionEdge): Edge {
  return { id: edge.id, source: edge.from_node_id, target: edge.to_node_id };
}
