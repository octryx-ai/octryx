import { buildTopologyDiagramFlow } from "./flowBuilderDefinition";
import {
  incidentIntakeNodes,
  incidentPlanNodes,
  repositoryImpactNodes,
  repositoryIntakeNodes,
} from "./flowBuilderOperationalTemplateNodes";
import {
  linearFlow,
  withTemplateMetadata,
  type FlowBuilderTemplate,
  type FlowBuilderTemplateMetadata,
} from "./flowBuilderTemplateTypes";

/** Template metadata of the incident triage flow. */
function incidentTriageMetadata(
  inputSchema: Record<string, string>,
): FlowBuilderTemplateMetadata {
  return {
    template_key: "incident-triage",
    category: "Operations",
    input_schema: inputSchema,
    expected_outputs: ["Triage plan", "Runtime evidence", "Approval requirement"],
    evidence_contract: {
      required_source_families: ["runtime_topology", "knowledge"],
      action_execution: "approval_required",
    },
    sample_test_case: {
      input:
        "Production payments latency is high, investigate impact and next safe steps.",
      expected:
        "Plan cites runtime/knowledge evidence and asks approval before changing systems.",
    },
    quality_gate_binding: {
      gate: "incident_action_approval_required",
      severity: "blocking",
    },
  };
}

export function incidentTriageTemplate(): FlowBuilderTemplate {
  const inputSchema = {
    incident: "string",
    service_hint: "string",
    severity: "string",
  };
  const nodes = [
    ...incidentIntakeNodes(inputSchema),
    ...incidentPlanNodes(),
  ];

  return {
    key: "incident-triage",
    name: "Incident Triage",
    description:
      "Classify incidents, collect runtime and knowledge evidence, and require approval before actions.",
    category: "Operations",
    definition: linearFlow(nodes, incidentTriageMetadata(inputSchema)),
  };
}

/** Template metadata of the repository change analysis flow. */
function repositoryChangeAnalysisMetadata(
  inputSchema: Record<string, string>,
): FlowBuilderTemplateMetadata {
  return {
    template_key: "repository-change-analysis",
    category: "Engineering",
    input_schema: inputSchema,
    expected_outputs: [
      "Change summary",
      "Commit/PR evidence",
      "Impact and open questions",
    ],
    evidence_contract: {
      required_source_families: ["repository", "commits_or_pull_requests"],
      no_generic_unfiltered_commit_dump: true,
    },
    sample_test_case: {
      input: "What did author-1 change recently in the repo-1 repository?",
      expected:
        "Answer is based on author-filtered Bitbucket commits and PR evidence.",
    },
    quality_gate_binding: {
      gate: "repository_evidence_required",
      severity: "blocking",
    },
  };
}

export function repositoryChangeAnalysisTemplate(): FlowBuilderTemplate {
  const inputSchema = {
    request: "string",
    repository_hint: "string",
    author_hint: "string",
  };
  const nodes = [
    ...repositoryIntakeNodes(inputSchema),
    ...repositoryImpactNodes(),
  ];

  return {
    key: "repository-change-analysis",
    name: "Repository Change Analysis",
    description:
      "Resolve repository/author evidence and summarize commits, PRs, impact, and gaps.",
    category: "Engineering",
    definition: linearFlow(nodes, repositoryChangeAnalysisMetadata(inputSchema)),
  };
}

export function topologyTemplate(
  provider: "aws" | "kubernetes",
): FlowBuilderTemplate {
  const isAws = provider === "aws";
  const key = `${provider}-topology-diagram-workflow`;
  return {
    key,
    name: isAws
      ? "AWS Topology Diagram Workflow"
      : "Kubernetes Topology Diagram Workflow",
    description: isAws
      ? "Evidence-rendered AWS topology diagram flow."
      : "Evidence-rendered Kubernetes topology diagram flow.",
    category: "Operations",
    definition: withTemplateMetadata(buildTopologyDiagramFlow(provider), {
      template_key: key,
      category: "Operations",
      input_schema: { request: "string", scope_hint: "string" },
      expected_outputs: [
        "Topology summary",
        "Rendered diagram artifact",
        "Known topology gaps",
      ],
      evidence_contract: {
        required_source_families: [
          isAws ? "aws_runtime_inventory" : "kubernetes_runtime_inventory",
        ],
        diagram_source: isAws
          ? "aws_topology_snapshot"
          : "kubernetes_topology_snapshot",
      },
      sample_test_case: {
        input: isAws
          ? "Create an AWS topology diagram."
          : "Create a Kubernetes topology diagram.",
        expected:
          "Diagram is rendered from runtime evidence rather than invented structure.",
      },
      quality_gate_binding: {
        gate: "topology_evidence_required",
        severity: "blocking",
      },
    }),
  };
}
