// CI/CD findings and pipeline stage traces of a Work item.

export type WorkCicdFinding = {
  id: string;
  work_item_id: string;
  provider_config_id?: string | null;
  pipeline_trace_id?: string | null;
  finding_type: string;
  status: string;
  event_status: string;
  severity: string;
  title: string;
  summary?: string | null;
  job_name?: string | null;
  build_number?: string | null;
  build_url?: string | null;
  branch_name?: string | null;
  commit_sha?: string | null;
  pr_url?: string | null;
  current_for_commit: boolean;
  stale_reason?: string | null;
  artifacts: Array<Record<string, unknown>>;
  comments: Array<Record<string, unknown>>;
  evidence: Record<string, unknown>;
  gate_results: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
  created_at?: string | null;
};

export type WorkCicdFindingsPayload = {
  items: WorkCicdFinding[];
  summary: Record<string, unknown>;
  agent_failure_context: Record<string, unknown>;
};

export type WorkCicdPipelineStageTrace = {
  stage_key: string;
  label: string;
  stage_order: number;
  status: string;
  result?: string | null;
  failure_type?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  log_excerpt: {
    text: string;
    truncated: boolean;
    original_length: number;
    limit: number;
  };
  artifacts: Array<Record<string, unknown>>;
  test_report: Record<string, unknown>;
  coverage: Record<string, unknown>;
  scan_report: Record<string, unknown>;
  evidence: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
};

export type WorkCicdPipelineTrace = {
  id: string;
  provider_config_id?: string | null;
  work_item_id: string;
  repository_profile_id?: string | null;
  job_name: string;
  job_url?: string | null;
  build_number?: string | null;
  build_url?: string | null;
  provider_type: string;
  branch_name?: string | null;
  commit_sha?: string | null;
  pr_url?: string | null;
  status: string;
  result?: string | null;
  triggered_by?: string | null;
  trigger_actor?: string | null;
  deployment_target?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  stages: WorkCicdPipelineStageTrace[];
  log_excerpt: Record<string, unknown>;
  artifacts: Array<Record<string, unknown>>;
  test_reports: Array<Record<string, unknown>>;
  coverage: Record<string, unknown>;
  scan_reports: Array<Record<string, unknown>>;
  failure_summary: Record<string, unknown>;
  agent_context: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at?: string | null;
};

export type WorkCicdPipelineTracesPayload = {
  items: WorkCicdPipelineTrace[];
  agent_failure_context: Record<string, unknown>;
};
