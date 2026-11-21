import type {
  FlowDefinitionJson,
  FlowDefinitionNode,
  FlowNodeType,
} from "./flowBuilderTypes";

export type FlowBuilderTemplate = {
  key: string;
  name: string;
  description: string;
  category: string;
  definition: FlowDefinitionJson;
};

export type FlowBuilderTemplateMetadata = {
  template_key: string;
  category: string;
  input_schema: Record<string, string>;
  expected_outputs: string[];
  evidence_contract: Record<string, unknown>;
  sample_test_case: Record<string, unknown>;
  quality_gate_binding: Record<string, unknown>;
};

export function flowNode(
  id: string,
  type: FlowNodeType,
  label: string,
  inputSchema: Record<string, string>,
  outputSchema: Record<string, string>,
  y: number,
  config: Record<string, unknown> = {},
): FlowDefinitionNode {
  return {
    id,
    type,
    label,
    input_schema: inputSchema,
    output_schema: outputSchema,
    config,
    position: { x: y % 240 === 0 ? 80 : 260, y },
  };
}

export function linearFlow(
  nodes: FlowDefinitionNode[],
  metadata: FlowBuilderTemplateMetadata,
): FlowDefinitionJson {
  return {
    schema_version: "2.0",
    nodes,
    edges: nodes.slice(1).map((node, index) => ({
      source_node_id: nodes[index].id,
      target_node_id: node.id,
    })),
    metadata: {
      template_key: metadata.template_key,
      category: metadata.category,
      purpose:
        metadata.expected_outputs?.length > 0
          ? `Produce ${metadata.expected_outputs.join(", ")}.`
          : undefined,
      sample_test_case: metadata.sample_test_case,
      quality_gate_binding: metadata.quality_gate_binding,
    },
    evidence_contract: metadata.evidence_contract,
    template_metadata: metadata,
  };
}

export function withTemplateMetadata(
  definition: FlowDefinitionJson,
  metadata: FlowBuilderTemplateMetadata,
): FlowDefinitionJson {
  return {
    ...definition,
    schema_version: "2.0",
    metadata: {
      ...(definition.metadata ?? {}),
      template_key: metadata.template_key,
      category: metadata.category,
      sample_test_case: metadata.sample_test_case,
      quality_gate_binding: metadata.quality_gate_binding,
    },
    evidence_contract: definition.evidence_contract ?? metadata.evidence_contract,
    template_metadata: metadata,
  };
}
