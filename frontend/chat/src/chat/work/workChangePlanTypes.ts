// Change plans for a Work item and the decisions taken on them.
import type { WorkChangeUnit, WorkReviewerCandidate } from "./workPullRequestTypes";
import type { WorkTransitionPreview } from "./workSyncWorkflowTypes";

export type WorkChangePlanStatus =
  | "draft"
  | "needs_clarification"
  | "ready_for_review"
  | "approved"
  | "rejected"
  | "superseded";

export type WorkChangePlan = {
  id: string;
  work_item_id: string;
  workflow_id?: string | null;
  supersedes_plan_id?: string | null;
  version: number;
  status: WorkChangePlanStatus;
  title: string;
  understood_request: string;
  assumptions: string[];
  open_questions: string[];
  affected_repositories: Array<Record<string, unknown>>;
  change_units: WorkChangeUnit[];
  proposed_branches: Array<Record<string, unknown>>;
  planned_files: Array<Record<string, unknown>>;
  validation_plan: Array<Record<string, unknown>>;
  security_risks: Array<Record<string, unknown>>;
  reviewer_recommendations: WorkReviewerCandidate[];
  required_approvals: Array<Record<string, unknown>>;
  expected_prs: Array<Record<string, unknown>>;
  rollback_plan: string;
  trace_refs: Array<Record<string, unknown>>;
  evidence: Record<string, unknown>;
  jira_sync_preview: WorkTransitionPreview["jira_sync_preview"] & {
    target_state?: string;
    source?: string;
    comment_body?: string;
    approval_url?: string;
  };
  created_by: string;
  updated_by?: string | null;
  approved_by?: string | null;
  decided_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  approved_at?: string | null;
  decided_at?: string | null;
};

export type WorkChangePlanDecision = {
  id: string;
  change_plan_id: string;
  work_item_id: string;
  actor_id: string;
  action: "approve" | "reject" | "request_clarification";
  from_status?: string | null;
  to_status: string;
  reason: string;
  required_changes: string[];
  jira_sync_preview: WorkChangePlan["jira_sync_preview"];
  evidence: Record<string, unknown>;
  created_at?: string | null;
};
