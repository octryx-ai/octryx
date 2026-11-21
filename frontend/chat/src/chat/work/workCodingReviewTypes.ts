// Coding review events, agent feedback, audit events, quality gates and audit reports.

export type WorkCodingReviewEventType =
  | "inline_comment"
  | "manual_edit"
  | "diagnostic"
  | "review_decision";

export type WorkCodingReviewEvent = {
  id: string;
  work_item_id: string;
  change_unit_id?: string | null;
  event_type: WorkCodingReviewEventType;
  file_path: string;
  line_number?: number | null;
  severity?: "info" | "low" | "medium" | "high" | "critical" | null;
  status: string;
  body: string;
  original_content?: string | null;
  updated_content?: string | null;
  metadata: Record<string, unknown>;
  agent_context: Record<string, unknown>;
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type WorkAgentFeedbackContext = {
  event_count: number;
  counts: Record<string, number>;
  changed_files: string[];
  human_edits: Array<Record<string, unknown>>;
  reviewer_comments: Array<Record<string, unknown>>;
  diagnostics: Array<Record<string, unknown>>;
  constraints: string[];
  agent_instruction: string;
};

export type WorkCodingReviewEventsPayload = {
  items: WorkCodingReviewEvent[];
  agent_feedback_context: WorkAgentFeedbackContext;
};

export type WorkCodingAuditEvent = {
  id: string;
  work_item_id: string;
  pipeline_run_id?: string | null;
  pipeline_stage_id?: string | null;
  review_event_id?: string | null;
  event_type: string;
  title: string;
  summary?: string | null;
  actor_kind: string;
  actor_id?: string | null;
  repository_name?: string | null;
  branch_name?: string | null;
  commit_sha?: string | null;
  pr_url?: string | null;
  evidence: Record<string, unknown>;
  gate_results: Array<Record<string, unknown>>;
  metadata: Record<string, unknown>;
  created_at?: string | null;
};

export type WorkCodingQualityGate = {
  key: string;
  label: string;
  status: "pass" | "block" | "missing" | "review_required" | string;
  blocking: boolean;
  reason: string;
  evidence: Record<string, unknown>;
};

export type WorkCodingPrSummary = {
  title: string;
  status: string;
  request: string;
  implementation: string[];
  files: string[];
  repositories: string[];
  branches: string[];
  tests: Array<Record<string, unknown>>;
  risks: WorkCodingQualityGate[];
  reviewers: string[];
  ready_to_open_pr: boolean;
};

export type WorkCodingAuditTimelineEvent = {
  id: string;
  kind: string;
  title: string;
  summary?: string | null;
  status?: string | null;
  created_at?: string | null;
  evidence: Record<string, unknown>;
};

export type WorkCodingAuditReport = {
  work_item_id: string;
  source_key: string;
  timeline: WorkCodingAuditTimelineEvent[];
  quality_gates: WorkCodingQualityGate[];
  quality_summary: {
    status: "passed" | "blocked" | "review_required" | string;
    total: number;
    blocking: number;
    counts: Record<string, number>;
  };
  pr_summary: WorkCodingPrSummary;
  evidence: Record<string, unknown>;
  audit_event?: WorkCodingAuditEvent;
};
