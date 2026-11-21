// Node lists of the person source evidence and release analysis flow templates.
import { flowNode } from "./flowBuilderTemplateTypes";
import type { FlowDefinitionNode } from "./flowBuilderTypes";

/** Person template: the question, alias normalization and identity resolution. */
export function personIdentityNodes(inputSchema: Record<string, string>): FlowDefinitionNode[] {
  return [
    flowNode("person-request", "trigger", "Person question", {}, inputSchema, 0, {
      trigger_type: "chat_question",
    }),
    flowNode(
      "normalize-person",
      "input_schema",
      "Normalize names and aliases",
      inputSchema,
      { request: "string", subject_hint: "string", subject_aliases: "array" },
      120,
    ),
    flowNode(
      "resolve-identity",
      "tool_step",
      "Resolve source identities",
      { request: "string", subject_hint: "string", subject_aliases: "array" },
      {
        request: "string",
        subject_aliases: "array",
        identity_candidates: "array",
        jira_user_evidence: "array",
      },
      240,
      { allowed_tools: ["search_jira_users", "search_bitbucket_users"] },
    ),
  ];
}

/** Person template: cross-source activity and the profile synthesis. */
export function personEvidenceNodes(): FlowDefinitionNode[] {
  return [
    flowNode(
      "collect-source-activity",
      "retrieval",
      "Collect cross-source activity",
      {
        request: "string",
        subject_aliases: "array",
        identity_candidates: "array",
        jira_user_evidence: "array",
      },
      {
        source_activity: "array",
        jira_user_evidence: "array",
        evidence_summary: "object",
        known_gaps: "array",
      },
      360,
      {
        allowed_tools: [
          "knowledge_search_by_user",
          "search_jira_tickets",
          "search_confluence",
          "list_recent_bitbucket_commits",
        ],
      },
    ),
    flowNode(
      "synthesize-profile",
      "agent_step",
      "Synthesize evidence-backed profile",
      {
        source_activity: "array",
        jira_user_evidence: "array",
        evidence_summary: "object",
        known_gaps: "array",
      },
      {
        profile_draft: "string",
        evidence_summary: "object",
        known_gaps: "array",
      },
      480,
      {
        prompt:
          "Write an evidence-backed profile of the subject from the collected source activity. Cite the "
          + "source of every statement, keep identity candidates apart until the evidence links them, and "
          + "list the known gaps.",
      },
    ),
  ];
}

/** Person template: the evidence gate and the answer. */
export function personAnswerNodes(): FlowDefinitionNode[] {
  return [
    flowNode(
      "evidence-gate",
      "evaluation",
      "Evidence completeness gate",
      {
        profile_draft: "string",
        evidence_summary: "object",
        known_gaps: "array",
      },
      {
        profile_draft: "string",
        evidence_summary: "object",
        known_gaps: "array",
        quality_passed: "boolean",
      },
      600,
      { quality_gate: "source_evidence_required" },
    ),
    flowNode(
      "person-answer",
      "output",
      "Return person profile with gaps",
      {
        profile_draft: "string",
        evidence_summary: "object",
        known_gaps: "array",
        quality_passed: "boolean",
      },
      {},
      720,
    ),
  ];
}

/** Release template: the question and the normalized intent. */
export function releaseIntakeNodes(inputSchema: Record<string, string>): FlowDefinitionNode[] {
  return [
    flowNode("release-request", "trigger", "Release question", {}, inputSchema, 0),
    flowNode(
      "normalize-release",
      "input_schema",
      "Normalize release intent",
      inputSchema,
      {
        request: "string",
        project_hint: "string",
        release_focus: "string",
        project_candidates: "array",
      },
      120,
    ),
  ];
}

/** Release template: project/version discovery and the FixVersion issues. */
export function releaseDiscoveryNodes(): FlowDefinitionNode[] {
  return [
    flowNode(
      "discover-projects",
      "tool_step",
      "Discover Jira projects and versions",
      {
        request: "string",
        project_hint: "string",
        release_focus: "string",
        project_candidates: "array",
      },
      {
        release_context: "object",
        project_candidates: "array",
        version_candidates: "array",
      },
      240,
      { allowed_tools: ["list_jira_projects", "list_jira_versions"] },
    ),
    flowNode(
      "collect-release-changes",
      "tool_step",
      "Collect FixVersion issues",
      {
        release_context: "object",
        project_candidates: "array",
        version_candidates: "array",
      },
      {
        release_context: "object",
        change_items: "array",
        known_gaps: "array",
      },
      360,
      { allowed_tools: ["search_jira_tickets", "knowledge_search"] },
    ),
  ];
}

/** Release template: the evidence gate and the answer. */
export function releaseAnswerNodes(): FlowDefinitionNode[] {
  return [
    flowNode(
      "release-evidence-gate",
      "evaluation",
      "Release evidence gate",
      { release_context: "object", change_items: "array", known_gaps: "array" },
      {
        release_context: "object",
        change_items: "array",
        known_gaps: "array",
        quality_passed: "boolean",
      },
      480,
      { quality_gate: "release_evidence_required" },
    ),
    flowNode(
      "release-answer",
      "output",
      "Return release answer",
      {
        release_context: "object",
        change_items: "array",
        known_gaps: "array",
        quality_passed: "boolean",
      },
      {},
      600,
    ),
  ];
}
