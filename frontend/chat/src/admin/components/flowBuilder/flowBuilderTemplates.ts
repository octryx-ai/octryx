import { safeKey } from "./flowBuilderDefinition";
import { incidentAnalysisTemplate } from "./flowBuilderIncidentAnalysisTemplate";
import {
  incidentTriageTemplate,
  repositoryChangeAnalysisTemplate,
  topologyTemplate,
} from "./flowBuilderOperationalTemplates";
import { knowledgeAnswerTemplate } from "./flowBuilderKnowledgeTemplate";
import { personSourceEvidenceTemplate, releaseAnalysisTemplate } from "./flowBuilderSourceTemplates";
import type { FlowBuilderTemplate } from "./flowBuilderTemplateTypes";

export const FLOW_BUILDER_TEMPLATES: FlowBuilderTemplate[] = [
  personSourceEvidenceTemplate(),
  releaseAnalysisTemplate(),
  knowledgeAnswerTemplate(),
  incidentTriageTemplate(),
  incidentAnalysisTemplate(),
  repositoryChangeAnalysisTemplate(),
  topologyTemplate("aws"),
  topologyTemplate("kubernetes"),
];

export function findFlowBuilderTemplate(key: string): FlowBuilderTemplate {
  return (
    FLOW_BUILDER_TEMPLATES.find((template) => template.key === key) ??
    FLOW_BUILDER_TEMPLATES[0]
  );
}

export function draftKeyForTemplate(template: FlowBuilderTemplate): string {
  return safeKey(template.key || template.name);
}
