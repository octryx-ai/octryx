import type { WorkCodingPipelineConfig } from "../work/workCodingPipelineTypes";
import { DEFAULT_REVIEW_STATUS, jsonFieldError, parseJsonObject, parseJsonObjectList, splitValues } from "./codingGovernanceForm";

export type PipelineForm = {
  id?: string;
  // The Workspace the pipeline belongs to; empty: every Workspace (platform admins only).
  project_id?: string | null;
  name: string;
  description: string;
  stages: string;
  required_stage_keys: string;
  controls: string;
  review_status: string;
  is_active: boolean;
};

export const DEFAULT_STAGES = [
  { key: "intake", label: "Intake and repository resolution", required: true },
  { key: "context_collection", label: "Context collection", required: true },
  { key: "change_plan", label: "Change plan generation", required: true },
  { key: "policy_preflight", label: "Policy preflight", required: true },
  { key: "branch_worktree", label: "Branch/worktree creation", required: true },
  { key: "implementation", label: "Implementation iterations", required: true },
  { key: "local_validation", label: "Local validation", required: true },
  { key: "diff_review", label: "Diff review and policy post-check", required: true },
  { key: "ci_cd", label: "CI/CD execution", required: false },
  { key: "human_feedback", label: "Human review feedback handling", required: true },
  { key: "pr_update", label: "PR creation/update", required: true },
  { key: "acceptance_closeout", label: "Acceptance state and closeout", required: true },
];

export const EMPTY_PIPELINE_FORM: PipelineForm = {
  name: "Enterprise coding pipeline",
  description: "Traceable plan-to-PR process.",
  stages: JSON.stringify(DEFAULT_STAGES, null, 2),
  required_stage_keys: DEFAULT_STAGES.filter((stage) => stage.required).map((stage) => stage.key).join("\n"),
  controls: JSON.stringify({ pause: true, resume: true, cancel: true }, null, 2),
  review_status: DEFAULT_REVIEW_STATUS,
  is_active: true,
};

export const PIPELINE_JSON_HELP = {
  stages: "Ordered steps of a coding session; each entry needs a key and a label, e.g. {\"key\": \"intake\", \"label\": \"Intake\"}.",
  controls: "Which run controls operators get: pause, resume, cancel (true or false).",
};

export function pipelineFormFromConfig(item: WorkCodingPipelineConfig): PipelineForm {
  return {
    id: item.id,
    project_id: item.project_id ?? null,
    name: item.name,
    description: item.description,
    stages: JSON.stringify(item.stages || [], null, 2),
    required_stage_keys: item.required_stage_keys.join("\n"),
    controls: JSON.stringify(item.controls || {}, null, 2),
    review_status: item.review_status,
    is_active: item.is_active,
  };
}

export function pipelineFormToPayload(form: PipelineForm): Partial<WorkCodingPipelineConfig> {
  return {
    id: form.id,
    project_id: form.project_id ?? null,
    name: form.name,
    description: form.description,
    stages: parseJsonObjectList(form.stages, "Stages JSON"),
    required_stage_keys: splitValues(form.required_stage_keys),
    controls: parseJsonObject(form.controls, "Controls JSON"),
    review_status: form.review_status,
    is_active: form.is_active,
  };
}

// Stage list for the guided step view; null while the stages JSON is invalid.
export function pipelineStageRows(stagesText: string): Array<{ key: string; label: string }> | null {
  if (jsonFieldError(stagesText, "objectList")) return null;
  return parseJsonObjectList(stagesText, "Stages JSON")
    .map((stage) => {
      const key = String(stage.key || "").trim();
      return { key, label: String(stage.label || key).trim() };
    })
    .filter((stage) => stage.key);
}
