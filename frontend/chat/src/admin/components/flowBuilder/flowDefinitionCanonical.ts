// Canonical form of a flow definition for the "unsaved changes" check. Both sides (the
// editor's working copy and the stored revision) go through the same function, so a stored
// revision that was merely loaded into the canvas compares equal to itself.
//
// Normalised — only what the editor derives on load (see flowCanvasMapping):
// - object key order and `undefined` values (JSON has neither);
// - edge endpoints `from_node_id`/`to_node_id` vs `source_node_id`/`target_node_id`;
// - the default edge id `source->target` the canvas assigns to an edge stored without an id;
// - the layout position the canvas assigns to a node stored without a position;
// - empty edge mappings/conditions, which the canvas omits.
// Everything else is authored content and compared as is: labels, config, schemas, mappings,
// conditions, node/edge lists and stored positions (a moved node is a real change, because
// positions are saved with the revision).
import { defaultEdgeId, layoutNodes } from "./flowCanvasMapping";
import type { FlowDefinitionEdge, FlowDefinitionJson } from "./flowBuilderTypes";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

function canonicalValue(value: unknown): Json | undefined {
  if (value === undefined || typeof value === "function") return undefined;
  if (value === null || typeof value !== "object") return value as Json;
  if (Array.isArray(value)) return value.map((item) => canonicalValue(item) ?? null);
  const result: { [key: string]: Json } = {};
  for (const key of Object.keys(value).sort()) {
    const item = canonicalValue((value as Record<string, unknown>)[key]);
    if (item !== undefined) result[key] = item;
  }
  return result;
}

function canonicalEdge(edge: FlowDefinitionEdge): Record<string, unknown> {
  const { id, from_node_id, to_node_id, source_node_id, target_node_id, ...rest } = edge;
  const source = from_node_id ?? source_node_id ?? "";
  const target = to_node_id ?? target_node_id ?? "";
  // The canvas omits empty mappings and conditions, so an empty stored value equals no value.
  for (const key of ["source_field", "target_field", "condition"] as const) {
    if (rest[key] === "" || rest[key] === null) delete rest[key];
  }
  return {
    ...rest,
    source_node_id: source,
    target_node_id: target,
    ...(id && id !== defaultEdgeId(source, target) ? { id } : {}),
  };
}

export function canonicalFlowDefinition(definition: FlowDefinitionJson | null | undefined): Json | undefined {
  const nodes = Array.isArray(definition?.nodes) ? definition.nodes : [];
  const edges = Array.isArray(definition?.edges) ? definition.edges : [];
  const positions = layoutNodes(nodes);
  return canonicalValue({
    ...(definition ?? {}),
    nodes: nodes.map((node) => ({ ...node, position: node.position ?? positions.get(node.id) ?? { x: 0, y: 0 } })),
    edges: edges.map(canonicalEdge),
  });
}

export function flowDefinitionsEqual(
  left: FlowDefinitionJson | null | undefined,
  right: FlowDefinitionJson | null | undefined,
): boolean {
  return JSON.stringify(canonicalFlowDefinition(left)) === JSON.stringify(canonicalFlowDefinition(right));
}
