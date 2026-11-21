// Flow run types: run and node traces, quality summaries, evaluations and test cases.

export type FlowRunTrace = {
  id: string;
  status: string;
  pattern_type: string;
  session_id?: string | null;
  parent_session_id?: string | null;
  project_id?: string | null;
  flow_definition_version_id: string;
  flow_node_id?: string | null;
  current_step_index?: number;
  total_steps?: number;
  child_session_ids?: string[];
  merged_output_json?: Record<string, unknown>;
  progress?: Record<string, unknown>;
  runtime_lease?: Record<string, unknown>;
  plan?: Record<string, unknown>;
  failure?: Record<string, unknown>;
  acceptance?: Record<string, unknown>;
  last_error?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
};

export type FlowNodeRunTrace = {
  id: string;
  flow_run_id?: string;
  flow_definition_version_id?: string;
  node_id: string;
  node_type: string;
  status: string;
  attempt: number;
  input: unknown;
  output: unknown;
  error?: string | null;
  evidence_summary?: Record<string, unknown>;
  artifact_refs?: Array<Record<string, unknown>>;
  trace_refs?: Record<string, unknown>;
  decision_trace?: Record<string, unknown>;
  token_usage?: Record<string, unknown>;
  cost_estimate?: Record<string, unknown>;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
};

export type FlowRunTracePayload = {
  run: FlowRunTrace;
  node_runs: FlowNodeRunTrace[];
};

export type FlowEvaluationRunSummary = {
  id: string;
  status: string;
  passed_count: number;
  failed_count: number;
  average_score?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export type FlowQualitySummary = {
  run: FlowRunTrace;
  flow_id: string;
  flow_definition_version_id: string;
  status: string;
  score: number;
  node_count: number;
  node_status_counts: Record<string, number>;
  failed_nodes: string[];
  evidence_count: number;
  artifact_count: number;
  token_usage: Record<string, number>;
  cost_estimate: Record<string, number>;
  warnings: Array<{ code: string; message: string }>;
  evaluation_runs: FlowEvaluationRunSummary[];
};

export type FlowQualityEvaluationPayload = {
  quality_summary: FlowQualitySummary;
  evaluation_run: FlowEvaluationRunSummary & {
    results?: Array<Record<string, unknown>>;
    gate_outcomes?: Array<Record<string, unknown>>;
  };
};

export type FlowTestCase = {
  id: string;
  name: string;
  description?: string;
  input: Record<string, unknown>;
  expected_output?: Record<string, unknown>;
  assertions?: Record<string, unknown>[];
  tags?: string[];
  last_run_id?: string | null;
  last_status?: string | null;
  last_evaluation_status?: string | null;
  last_passed?: boolean | null;
  last_output?: Record<string, unknown> | null;
  last_evaluation_summary?: {
    status: string;
    passed: boolean;
    total: number;
    passed_count: number;
    failed_count: number;
    warnings?: string[];
    results?: Record<string, unknown>[];
  } | null;
  changed_since_previous?: boolean;
  updated_at?: string | null;
};

export type FlowTestCaseListPayload = {
  flow_id: string;
  version_id: string;
  items: FlowTestCase[];
};

export type FlowTestCaseRunPayload = {
  test_case: FlowTestCase;
  run_id: string;
  status: string;
  passed?: boolean;
  evaluation_summary?: FlowTestCase["last_evaluation_summary"];
  assertion_results?: Record<string, unknown>[];
  output: Record<string, unknown>;
  trace?: FlowRunTracePayload;
};

export type FlowTestCaseBatchPayload = {
  flow_id: string;
  version_id: string;
  count: number;
  passed: number;
  failed?: number;
  results: FlowTestCaseRunPayload[];
};
