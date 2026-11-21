// Flow builder templates: person source evidence and release analysis.
import {
  personAnswerNodes,
  personEvidenceNodes,
  personIdentityNodes,
  releaseAnswerNodes,
  releaseDiscoveryNodes,
  releaseIntakeNodes,
} from "./flowBuilderSourceTemplateNodes";
import {
  linearFlow,
  type FlowBuilderTemplate,
  type FlowBuilderTemplateMetadata,
} from "./flowBuilderTemplateTypes";

/** Template metadata of the person source evidence flow. */
function personSourceEvidenceMetadata(
  inputSchema: Record<string, string>,
): FlowBuilderTemplateMetadata {
  return {
    template_key: "person-source-evidence-research",
    category: "Research",
    input_schema: inputSchema,
    expected_outputs: [
      "Evidence-backed person profile",
      "Source distribution and representative work",
      "Known gaps when a connector has no matching evidence",
    ],
    evidence_contract: {
      required_source_families: [
        "identity",
        "work_items",
        "knowledge",
        "code_activity",
      ],
      minimum_direct_evidence_families: 2,
    },
    sample_test_case: {
      input: "Who is person-1?",
      expected:
        "Answer includes Jira work, Confluence/Knowledge activity, Bitbucket activity, and gaps.",
    },
    quality_gate_binding: {
      gate: "source_evidence_required",
      severity: "blocking",
    },
  };
}

export function personSourceEvidenceTemplate(): FlowBuilderTemplate {
  const inputSchema = { request: "string", subject_hint: "string" };
  const nodes = [
    ...personIdentityNodes(inputSchema),
    ...personEvidenceNodes(),
    ...personAnswerNodes(),
  ];

  return {
    key: "person-source-evidence-research",
    name: "Person Source-Evidence Research",
    description:
      "Find who a person is across Jira, Confluence, Bitbucket, and Knowledge with explicit evidence gaps.",
    category: "Research",
    definition: linearFlow(nodes, personSourceEvidenceMetadata(inputSchema)),
  };
}

/** Template metadata of the release analysis flow. */
function releaseAnalysisMetadata(
  inputSchema: Record<string, string>,
): FlowBuilderTemplateMetadata {
  return {
    template_key: "release-analysis",
    category: "Delivery",
    input_schema: inputSchema,
    expected_outputs: [
      "Selected release/version",
      "Linked changes",
      "Evidence gaps",
    ],
    evidence_contract: {
      required_source_families: [
        "jira_projects",
        "jira_versions",
        "fix_version_issues",
      ],
    },
    sample_test_case: {
      input: "What changes are on the next release?",
      expected:
        "The answer identifies the next planned version and lists Jira-backed changes.",
    },
    quality_gate_binding: {
      gate: "release_evidence_required",
      severity: "blocking",
    },
  };
}

export function releaseAnalysisTemplate(): FlowBuilderTemplate {
  const inputSchema = {
    request: "string",
    project_hint: "string",
    release_focus: "string",
  };
  const nodes = [
    ...releaseIntakeNodes(inputSchema),
    ...releaseDiscoveryNodes(),
    ...releaseAnswerNodes(),
  ];

  return {
    key: "release-analysis",
    name: "Release Analysis",
    description:
      "Answer latest/next release questions from Jira versions and linked change evidence.",
    category: "Delivery",
    definition: linearFlow(nodes, releaseAnalysisMetadata(inputSchema)),
  };
}
