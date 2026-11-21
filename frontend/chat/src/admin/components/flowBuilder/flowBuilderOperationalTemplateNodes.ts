// Node lists of the incident triage and repository change analysis flow templates.
import { flowNode } from "./flowBuilderTemplateTypes";
import type { FlowDefinitionNode } from "./flowBuilderTypes";

/** Incident template: intake, classification and runtime signals. */
export function incidentIntakeNodes(inputSchema: Record<string, string>): FlowDefinitionNode[] {
  return [
    flowNode("incident-trigger", "trigger", "Incident intake", {}, inputSchema, 0),
    flowNode(
      "classify-incident",
      "router",
      "Classify incident path",
      inputSchema,
      {
        incident: "string",
        service_hint: "string",
        severity: "string",
        triage_path: "string",
      },
      120,
    ),
    flowNode(
      "collect-runtime-signals",
      "tool_step",
      "Collect runtime signals",
      {
        incident: "string",
        service_hint: "string",
        severity: "string",
        triage_path: "string",
      },
      {
        incident_context: "object",
        runtime_signals: "array",
        known_gaps: "array",
      },
      240,
      {
        allowed_tools: [
          "aws_topology_snapshot",
          "kubernetes_topology_snapshot",
          "knowledge_search",
        ],
      },
    ),
  ];
}

/** Incident template: the triage plan, operator approval and the output. */
export function incidentPlanNodes(): FlowDefinitionNode[] {
  return [
    flowNode(
      "triage-plan",
      "agent_step",
      "Draft triage plan",
      {
        incident_context: "object",
        runtime_signals: "array",
        known_gaps: "array",
      },
      {
        triage_plan: "string",
        evidence_summary: "object",
        required_approvals: "array",
      },
      360,
      { policy: "incident_triage_evidence_first" },
    ),
    flowNode(
      "operator-approval",
      "approval",
      "Operator approval",
      {
        triage_plan: "string",
        evidence_summary: "object",
        required_approvals: "array",
      },
      {
        triage_plan: "string",
        evidence_summary: "object",
        approved: "boolean",
      },
      480,
      { approval_policy: "human_required_for_change_actions" },
    ),
    flowNode(
      "incident-output",
      "output",
      "Return triage plan",
      {
        triage_plan: "string",
        evidence_summary: "object",
        approved: "boolean",
      },
      {},
      600,
    ),
  ];
}

/** Repository template: the question, repository/author resolution and activity. */
export function repositoryIntakeNodes(inputSchema: Record<string, string>): FlowDefinitionNode[] {
  return [
    flowNode("repo-request", "trigger", "Repository change question", {}, inputSchema, 0),
    flowNode(
      "resolve-repository",
      "tool_step",
      "Resolve repository and author",
      inputSchema,
      {
        request: "string",
        repository_candidates: "array",
        author_candidates: "array",
      },
      120,
      { allowed_tools: ["search_bitbucket_users", "list_bitbucket_repositories"] },
    ),
    flowNode(
      "collect-repo-activity",
      "tool_step",
      "Collect commits and pull requests",
      {
        request: "string",
        repository_candidates: "array",
        author_candidates: "array",
      },
      { repo_activity: "array", pull_requests: "array", known_gaps: "array" },
      240,
      {
        allowed_tools: [
          "list_recent_bitbucket_commits",
          "list_bitbucket_pull_requests",
        ],
      },
    ),
  ];
}

/** Repository template: impact analysis, the evidence gate and the output. */
export function repositoryImpactNodes(): FlowDefinitionNode[] {
  return [
    flowNode(
      "analyze-impact",
      "agent_step",
      "Analyze code-change impact",
      { repo_activity: "array", pull_requests: "array", known_gaps: "array" },
      {
        impact_summary: "string",
        evidence_summary: "object",
        follow_up_questions: "array",
      },
      360,
      { policy: "repository_change_evidence" },
    ),
    flowNode(
      "repo-evidence-gate",
      "evaluation",
      "Repository evidence gate",
      {
        impact_summary: "string",
        evidence_summary: "object",
        follow_up_questions: "array",
      },
      {
        impact_summary: "string",
        evidence_summary: "object",
        follow_up_questions: "array",
        quality_passed: "boolean",
      },
      480,
      { quality_gate: "repository_evidence_required" },
    ),
    flowNode(
      "repo-output",
      "output",
      "Return change analysis",
      {
        impact_summary: "string",
        evidence_summary: "object",
        follow_up_questions: "array",
        quality_passed: "boolean",
      },
      {},
      600,
    ),
  ];
}
