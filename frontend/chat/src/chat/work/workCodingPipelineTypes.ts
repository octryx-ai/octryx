// Repository profiles and the coding pipeline: stages, runs, workspaces, config and traces.

export type WorkRepositoryProfile = {
  id: string;
  project_id?: string | null;
  code_repository_id?: string | null;
  technology_baseline_id?: string | null;
  name: string;
  provider: string;
  repository_url?: string | null;
  default_branch?: string | null;
  protected_branches: string[];
  jira_project_keys: string[];
  service_description: string;
  owners: string[];
  default_reviewers: string[];
  branch_naming_rule: string;
  pr_target_branch?: string | null;
  required_pipelines: string[];
  required_tests: string[];
  setup_commands: string[];
  build_commands: string[];
  test_commands: string[];
  lint_commands: string[];
  format_commands: string[];
  package_commands: string[];
  local_run_commands: string[];
  cleanup_commands: string[];
  builder_runtime_image?: string | null;
  local_toolchain: string[];
  required_env_vars: string[];
  secret_references: string[];
  protected_paths: string[];
  hotspot_files: string[];
  artifact_paths: string[];
  coverage_report_paths: string[];
  test_report_paths: string[];
  multi_repo_dependencies: Array<Record<string, unknown>>;
  risk_tags: string[];
  important_paths: string[];
  profile_source: string;
  review_status: string;
  is_active: boolean;
};

export type WorkCodingPipelineStage = {
  id: string;
  run_id: string;
  stage_key: string;
  label: string;
  stage_order: number;
  status: string;
  required: boolean;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  evidence: Array<Record<string, unknown>>;
  required_actions: string[];
  policy_refs: Array<Record<string, unknown>>;
  started_at?: string | null;
  completed_at?: string | null;
};

export type WorkCodingPipelineRun = {
  id: string;
  work_item_id: string;
  config_id?: string | null;
  status: string;
  current_stage_key?: string | null;
  control_state: string;
  summary: Record<string, unknown>;
  recovery_state: Record<string, unknown>;
  stages: WorkCodingPipelineStage[];
  started_at?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
};

export type WorkCodingWorkspace = {
  id: string;
  work_item_id: string;
  pipeline_run_id?: string | null;
  change_unit_id?: string | null;
  repository_profile_id?: string | null;
  session_id?: string | null;
  provider: string;
  provider_instance?: string | null;
  project_key?: string | null;
  repository_name?: string | null;
  repository_slug?: string | null;
  repository_url?: string | null;
  base_branch?: string | null;
  resolved_base_branch?: string | null;
  feature_branch?: string | null;
  base_commit?: string | null;
  workspace_path?: string | null;
  source_repository_root?: string | null;
  source_evidence_cutoff?: string | null;
  restart_generation: number;
  status: string;
  evidence: Record<string, unknown>;
  is_active: boolean;
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type WorkCodingPipelineConfig = {
  id: string;
  name: string;
  description: string;
  project_id?: string | null;
  scope: Record<string, unknown>;
  stages: Array<Record<string, unknown>>;
  required_stage_keys: string[];
  controls: Record<string, unknown>;
  review_status: string;
  is_active: boolean;
};

export type WorkCodingPipelineTrace = {
  work_item_id: string;
  run: WorkCodingPipelineRun | null;
  stages: WorkCodingPipelineStage[];
  available_configs: WorkCodingPipelineConfig[];
};
