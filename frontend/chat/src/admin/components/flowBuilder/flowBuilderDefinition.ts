import type { FlowDefinitionJson, FlowDefinitionNode } from "./flowBuilderTypes";

export function safeKey(value: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 120) || "governed-flow"
  );
}

// The flow's topology variant is its own tool steps.
export function buildTopologyDiagramFlow(
  provider: "aws" | "kubernetes",
): FlowDefinitionJson {
  const isAws = provider === "aws";
  const source = isAws
    ? "aws_topology_snapshot"
    : "kubernetes_topology_snapshot";
  const shapeLibrary = isAws ? "aws4" : "kubernetes";
  const topic = isAws ? "AWS Topology" : "Kubernetes Topology";
  const nodes: FlowDefinitionNode[] = [
    {
      id: "topology-request",
      type: "trigger",
      label: "Topology diagram request",
      output_schema: { user_message: "string" },
      position: { x: 0, y: 0 },
    },
    {
      id: "collect-topology",
      type: "tool_step",
      label: `Collect ${topic} snapshot`,
      input_schema: { user_message: "string" },
      output_schema: { diagram_brief: "object", topology_summary: "object" },
      config: { tool: source },
      position: { x: 0, y: 110 },
    },
    {
      id: "load-shapes",
      type: "tool_step",
      label: `Load ${shapeLibrary} shapes`,
      input_schema: { diagram_brief: "object", topology_summary: "object" },
      output_schema: { shape_library: "object" },
      config: { tool: "get_shape_library", library: shapeLibrary },
      position: { x: 0, y: 220 },
    },
    {
      id: "create-overview",
      type: "tool_step",
      label: "Create overview diagram",
      input_schema: { shape_library: "object" },
      output_schema: { diagram_id: "string" },
      config: { tool: "create_diagram", renderer: "evidence_rendered_xml" },
      position: { x: 0, y: 330 },
    },
    {
      id: "create-details",
      type: "agent_step",
      label: "Create focused details when large",
      input_schema: { diagram_id: "string" },
      output_schema: { detail_diagrams: "array" },
      config: { policy: "snapshot_candidate_details" },
      position: { x: 0, y: 440 },
    },
    {
      id: "final-response",
      type: "output",
      label: "Return diagram artifacts",
      input_schema: { detail_diagrams: "array" },
      position: { x: 0, y: 550 },
    },
  ];
  return {
    nodes,
    edges: nodes.slice(1).map((node, index) => ({
      from_node_id: nodes[index].id,
      to_node_id: node.id,
    })),
  };
}

export function parseJsonObject<T>(value: string): T {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON must be an object.");
  }
  return parsed as T;
}
