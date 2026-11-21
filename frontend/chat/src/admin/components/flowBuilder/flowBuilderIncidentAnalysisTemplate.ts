import incidentAnalysis from "./templates/incidentAnalysis.json" with { type: "json" };
import type { FlowDefinitionJson } from "./flowBuilderTypes";
import type { FlowBuilderTemplate } from "./flowBuilderTemplateTypes";

/**
 * "Incident-Analyse": intake → analysis → note → optional reporter question.
 * The definition is the JSON file the backend validator checks
 * (backend/tests/work_item_analysis/test_workflow_template.py); the run itself is
 * the governed work item analysis (work_item_analyze).
 */
export function incidentAnalysisTemplate(): FlowBuilderTemplate {
  return {
    key: incidentAnalysis.key,
    name: incidentAnalysis.name,
    description: incidentAnalysis.description,
    category: incidentAnalysis.category,
    definition: incidentAnalysis.definition as unknown as FlowDefinitionJson,
  };
}
