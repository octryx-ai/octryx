import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkChangeUnit, WorkReviewerCandidate, WorkReviewerRecommendationPayload } from "../work/workPullRequestTypes";
import type { WorkCicdFindingsPayload, WorkCicdPipelineTracesPayload } from "../work/workCicdTypes";
import type { WorkCodingAuditReport, WorkCodingReviewEventsPayload } from "../work/workCodingReviewTypes";
import type { WorkCodingPipelineTrace, WorkCodingWorkspace } from "../work/workCodingPipelineTypes";
import type { WorkItem } from "../work/workItemTypes";
import type { WorkStateEvent } from "../work/workSyncWorkflowTypes";

export type CodingSessionState =
  | "draft"
  | "planned"
  | "approved"
  | "implementing"
  | "blocked"
  | "testing"
  | "review_ready"
  | "pr_open"
  | "changes_requested"
  | "needs_replan"
  | "needs_human_review"
  | "completed"
  | "cancelled";

export type CodingSessionTone = "active" | "running" | "attention" | "danger" | "neutral";

export type CodingSessionPhase =
  | "ready_to_plan"
  | "planning"
  | "ready_to_implement"
  | "implementing"
  | "validating"
  | "reviewing"
  | "completed"
  | "blocked";

export type CodingSessionSummary = {
  id: string;
  sourceKey: string;
  title: string;
  state: CodingSessionState;
  tone: CodingSessionTone;
  statusLabel: string;
  workItem: WorkItem;
  phase: CodingSessionPhase;
  nextAction: string;
  blockerCount: number;
  // Recorded records only: never plan fields, planned files, repositories or branches.
  recordedEvidenceCount: number;
  isCodingRelevant: boolean;
  repositories: string[];
  branches: string[];
  pullRequests: string[];
  plannedFileCount: number;
  validation: CodingValidationEvidence;
  approvals: CodingApprovalEvidence;
  auditCount: number;
  agentSessions: CodingAgentChatSession[];
  latestAgentSession: CodingAgentChatSession | null;
  latestPlanStatus?: string | null;
  updatedAt?: string | null;
  // The coding audit's reviewer verdict for the latest plan; "unavailable" is unknown, never zero.
  review: CodingReviewSummary;
};

// Work review only: never Work Plan approval, execution authorization or pull-request readiness.
export type CodingReviewVerdict = "pass" | "block" | "review_required" | "missing";

export type CodingReviewSummary =
  | { status: CodingReviewVerdict; reason: string; planId: string | null; planVersion: number | null }
  // not_loaded: no verdict was delivered; invalid: malformed or bound to another plan version;
  // refreshing: a new decision was saved and the verdict is being re-read; refresh_failed: that failed.
  | { status: "unavailable"; cause: "not_loaded" | "invalid" | "refreshing" | "refresh_failed" };

// Planned checks versus recorded validation. `null` = not recorded or malformed (unknown);
// 0 = recorded zero. `results` are explicit source validation results with their outcome;
// `toolCalls` are agent tool calls the backend classifies as validation by tool name. A tool call is
// not a test result, so only `results` can establish passed or failed validation.
export type CodingValidationEvidence = {
  planned: number;
  // `unrecognized`: entries in the list that are not readable records; they keep the outcome open.
  results: { recorded: number | null; passed: number | null; failed: number | null; unrecognized: number | null };
  toolCalls: { recorded: number | null; failed: number | null };
};

// Required approvals (plan intent) versus approval records (`source_fields.approvals`), read by their
// explicit decision: only an approved/granted record counts as granted.
export type CodingApprovalEvidence = {
  required: number;
  recorded: number | null;
  granted: number | null;
  rejected: number | null;
  unrecognized: number | null;
  // True only when every required approval type is matched by its own granted record of that type
  // and no record is rejected, undecided or unreadable (presentation only, not a runtime policy).
  requirementsMet: boolean;
};

export type CodingAgentChatSession = {
  id: string;
  status: string;
  run_status?: string | null;
  agent_type: string;
  chat_url: string;
  event_type?: string | null;
  event_id?: string | null;
  started_at?: string | null;
  pipeline_run_id?: string | null;
  change_plan_id?: string | null;
  restart?: boolean;
  restart_reason?: string | null;
};

export type CodingSessionDetailData = {
  workItem: WorkItem | null;
  changePlans: WorkChangePlan[];
  changeUnits: WorkChangeUnit[];
  reviewerPayload: WorkReviewerRecommendationPayload | null;
  stateEvents: WorkStateEvent[];
  pipelineTrace: WorkCodingPipelineTrace | null;
  reviewEventsPayload: WorkCodingReviewEventsPayload | null;
  auditReport: WorkCodingAuditReport | null;
  cicdPipelineTraces: WorkCicdPipelineTracesPayload | null;
  cicdFindings: WorkCicdFindingsPayload | null;
  observability: WorkCodingObservability | null;
};

export type WorkCodingObservability = {
  schema: "coding_observability.v1";
  work_item_id: string;
  source_key: string;
  generated_from: {
    agent_sessions: number;
    usage_events: number;
    tool_calls: number;
    turn_traces: number;
    coding_audit_events: number;
    platform_audit_events: number;
  };
  summary: {
    status: string;
    agent_session_count: number;
    llm_call_count: number;
    turn_trace_count: number;
    tool_call_count: number;
    failed_tool_call_count: number;
    coding_audit_event_count: number;
    platform_audit_event_count: number;
    mutation_event_count: number;
    validation_event_count: number;
    repeated_tool_call_count: number;
    total_tokens: number;
    total_cost: string;
    latest_stop_reason?: string | null;
    next_observation: string;
  };
  agent_sessions: CodingAgentChatSession[];
  usage: {
    total: {
      events: number;
      tokens_in: number;
      tokens_out: number;
      tokens_total: number;
      cost: string;
    };
    by_model: WorkCodingUsageBucket[];
    by_session: WorkCodingUsageBucket[];
  };
  tools: {
    total: number;
    success: number;
    failed: number;
    by_kind: Record<string, number>;
    by_name: WorkCodingToolBucket[];
    repeated_calls: WorkCodingRepeatedToolCall[];
  };
  turns: {
    total: number;
    latest_stop_reason?: string | null;
    by_model: Array<{ key: string; count: number }>;
  };
  audit: {
    coding_event_count: number;
    platform_event_count: number;
    coding_events_by_type: Record<string, number>;
    platform_events_by_action: Record<string, number>;
  };
  timeline: WorkCodingObservabilityEvent[];
};

export type WorkCodingUsageBucket = {
  key: string;
  provider?: string | null;
  model?: string | null;
  session_id?: string | null;
  events: number;
  tokens_in: number;
  tokens_out: number;
  tokens_total: number;
  cost: string;
};

export type WorkCodingToolBucket = {
  tool_name: string;
  count: number;
  success: number;
  failed: number;
  total_duration_ms: number;
  kind: string;
  latest_status: string;
  latest_at?: string | null;
};

export type WorkCodingRepeatedToolCall = {
  tool_name: string;
  count: number;
  first_at?: string | null;
  latest_at?: string | null;
  parameters_preview: Record<string, unknown>;
};

export type WorkCodingObservabilityEvent = {
  id: string;
  kind: string;
  title: string;
  status: string;
  session_id?: string | null;
  created_at?: string | null;
  summary?: string;
  evidence?: Record<string, unknown>;
};

export type CodingAgentExecutionResult = {
  status: "started" | "blocked";
  work_item_id: string;
  source_key: string;
  change_plan_id: string;
  work_url?: string;
  coding_url?: string;
  next_actions?: Array<{
    key: string;
    label: string;
    url: string;
  }>;
  pipeline_run: Record<string, unknown>;
  workspaces?: WorkCodingWorkspace[];
  blockers: Array<Record<string, unknown>>;
  session: {
    id: string;
    status: string;
    agent_type: string;
    chat_url: string;
  } | null;
  reason?: string;
};

export type CodingSessionTab =
  | "overview"
  | "process"
  | "plan"
  | "changes"
  | "tests"
  | "reviews"
  | "policy"
  // The session reads as steps; these open the Pull request step and the Details section.
  | "pullRequest"
  | "details";

export type CodingReviewer = WorkReviewerCandidate;
