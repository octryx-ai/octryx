// Pure steps of the flow canvas edits: the edge a "Connect" creates and the copy "Duplicate" adds.
import type { RfEdge, RfNode } from "./flowCanvasMapping";

// A new edge between two nodes; a single output or input field is mapped right away.
export function connectionEdge(sourceNode: RfNode, targetNode: RfNode, edgeId: string): RfEdge {
  const sourceFields = Object.keys(sourceNode.data.output_schema ?? {});
  const targetFields = Object.keys(targetNode.data.input_schema ?? {});
  return {
    id: edgeId,
    source: sourceNode.id,
    target: targetNode.id,
    data: {
      sourceField: sourceFields.length === 1 ? sourceFields[0] : undefined,
      targetField: targetFields.length === 1 ? targetFields[0] : undefined,
    },
  };
}

// The nodes after duplicating `source`: the source deselected and a selected copy beside it.
export function withDuplicate(nodes: RfNode[], source: RfNode, id: string): RfNode[] {
  const duplicate: RfNode = {
    ...source,
    id,
    position: { x: source.position.x + 36, y: source.position.y + 48 },
    selected: true,
    data: {
      ...source.data,
      id,
      label: `${source.data.label ?? source.id} copy`,
      selected: true,
    },
  };
  const updatedNodes = nodes.map((node) =>
    node.id === source.id
      ? { ...node, selected: false, data: { ...node.data, selected: false } }
      : node,
  );
  return [...updatedNodes, duplicate];
}
