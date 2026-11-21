import { safeKey } from "./flowBuilderDefinition";
import { FLOW_BUILDER_TEMPLATES } from "./flowBuilderTemplates";
import type { FlowDefinitionJson } from "./flowBuilderTypes";

export const GLOBAL_WORKFLOW_SCOPE = "__global__";
export const BASIC_WORKFLOW_STARTER = "__basic__";

export function basicWorkflowDefinition(): FlowDefinitionJson {
  return {
    schema_version: "2.0",
    nodes: [
      { id: "input", type: "trigger", label: "Start", output_schema: { request: "string" }, config: { trigger_type: "manual" }, position: { x: 80, y: 80 } },
      { id: "output", type: "output", label: "Return result", input_schema: { request: "string" }, position: { x: 380, y: 80 } },
    ],
    edges: [{ source_node_id: "input", target_node_id: "output" }],
  };
}

export function buildNewFlowPayload(name: string, scope: string, templateKey: string, suffix: string) {
  if (!name.trim()) throw new Error("Name the workflow before continuing.");
  if (!scope) throw new Error("Choose a workspace or explicitly choose Global.");
  const template = FLOW_BUILDER_TEMPLATES.find((item) => item.key === templateKey);
  if (templateKey !== BASIC_WORKFLOW_STARTER && !template) throw new Error("Choose a supported starting point.");
  return {
    name: name.trim(),
    key: `${safeKey(name).slice(0, 130)}-${suffix}`,
    project_id: scope === GLOBAL_WORKFLOW_SCOPE ? null : scope,
    description: template?.description || "A manual workflow with a connected start and result. Add the steps your task needs.",
    definition: template ? structuredClone(template.definition) : basicWorkflowDefinition(),
    runtime_settings: { authoring_mode: "visual_builder", template_key: template?.key ?? null },
    policy_bindings: { validation_required: true },
  };
}
