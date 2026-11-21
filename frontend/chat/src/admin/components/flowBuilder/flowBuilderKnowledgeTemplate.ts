// Flow builder template: knowledge answer with citation and evidence gate.
import {
  flowNode,
  linearFlow,
  type FlowBuilderTemplate,
} from "./flowBuilderTemplateTypes";

type FlowNode = ReturnType<typeof flowNode>;

/** The question, the knowledge search and the source details. */
function knowledgeSearchNodes(inputSchema: Record<string, string>): FlowNode[] {
  return [
    flowNode("knowledge-request", "trigger", "Knowledge question", {}, inputSchema, 0),
    flowNode(
      "knowledge-search",
      "retrieval",
      "Search project knowledge",
      inputSchema,
      {
        request: "string",
        evidence_records: "array",
        source_keys: "array",
        known_gaps: "array",
      },
      120,
      {
        allowed_tools: [
          "list_project_knowledge_keys",
          "knowledge_graph_query",
          "knowledge_search",
        ],
      },
    ),
    flowNode(
      "knowledge-detail",
      "tool_step",
      "Load source details",
      {
        request: "string",
        evidence_records: "array",
        source_keys: "array",
        known_gaps: "array",
      },
      {
        evidence_records: "array",
        source_details: "array",
        known_gaps: "array",
      },
      240,
      { allowed_tools: ["knowledge_get"] },
    ),
  ];
}

/** The drafted answer, its citation gate and the output. */
function knowledgeAnswerNodes(): FlowNode[] {
  return [
    flowNode(
      "answer-with-sources",
      "agent_step",
      "Draft source-backed answer",
      {
        evidence_records: "array",
        source_details: "array",
        known_gaps: "array",
      },
      { answer_draft: "string", cited_sources: "array", known_gaps: "array" },
      360,
      { policy: "evidence_grounded_answer" },
    ),
    flowNode(
      "knowledge-evidence-gate",
      "evaluation",
      "Citation and gap gate",
      { answer_draft: "string", cited_sources: "array", known_gaps: "array" },
      {
        answer_draft: "string",
        cited_sources: "array",
        known_gaps: "array",
        quality_passed: "boolean",
      },
      480,
      { quality_gate: "citations_required" },
    ),
    flowNode(
      "knowledge-answer",
      "output",
      "Return answer",
      {
        answer_draft: "string",
        cited_sources: "array",
        known_gaps: "array",
        quality_passed: "boolean",
      },
      {},
      600,
    ),
  ];
}

export function knowledgeAnswerTemplate(): FlowBuilderTemplate {
  const inputSchema = { request: "string", project_id: "string" };
  const nodes = [...knowledgeSearchNodes(inputSchema), ...knowledgeAnswerNodes()];

  return {
    key: "knowledge-answer-with-evidence-gate",
    name: "Knowledge Answer With Evidence Gate",
    description:
      "Use Knowledge Base evidence, source details, citations, and explicit gaps before answering.",
    category: "Knowledge",
    definition: linearFlow(nodes, {
      template_key: "knowledge-answer-with-evidence-gate",
      category: "Knowledge",
      input_schema: inputSchema,
      expected_outputs: [
        "Source-backed answer",
        "Cited source keys",
        "Known evidence gaps",
      ],
      evidence_contract: {
        required_source_families: ["knowledge_search", "knowledge_detail"],
        minimum_cited_sources: 1,
      },
      sample_test_case: {
        input: "What do we know about the release process of product-1?",
        expected:
          "Answer cites Knowledge records and states missing evidence instead of guessing.",
      },
      quality_gate_binding: { gate: "citations_required", severity: "blocking" },
    }),
  };
}
