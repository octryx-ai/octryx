// Change units, pull requests, their coordination and reviewer recommendations.

export type WorkChangeUnit = {
  id: string;
  work_item_id: string;
  repository_profile_id?: string | null;
  repository_name: string;
  branch_name: string;
  scope: string;
  expected_paths: string[];
  validation_commands: string[];
  reviewer_policy: Record<string, unknown>;
  pr_link?: string | null;
  dependency_order: number;
  status: string;
  missing_profile_fields: string[];
};

export type WorkPullRequestMismatch = {
  type: string;
  severity: string;
  message: string;
  details?: Record<string, unknown>;
};

export type WorkPullRequest = {
  id: string;
  work_item_id?: string | null;
  change_unit_id?: string | null;
  repository_profile_id?: string | null;
  provider: string;
  provider_instance: string;
  project_key?: string | null;
  repository_slug: string;
  repository_url?: string | null;
  pr_id: string;
  pr_key?: string | null;
  pr_url: string;
  title: string;
  source_branch?: string | null;
  target_branch?: string | null;
  status: string;
  author: Record<string, unknown>;
  reviewers: unknown[];
  approvals: unknown[];
  build_status?: string | null;
  mergeability?: string | null;
  linked_jira_keys: string[];
  mismatches: WorkPullRequestMismatch[];
  raw_summary: Record<string, unknown>;
  source_created_at?: string | null;
  source_updated_at?: string | null;
  last_synced_at?: string | null;
  // The last read of the git host (backend); a failed read keeps the last known status.
  refresh?: WorkPullRequestRefresh | null;
};

export type WorkPullRequestRefresh = {
  status?: "ok" | "partial" | "failed" | null;
  error_code?: string | null;
  error?: string | null;
  attempted_at?: string | null;
  requested_at?: string | null;
};

export type WorkReviewerEvidence = {
  kind: string;
  points: number;
  reason: string;
  details?: Record<string, unknown>;
};

export type WorkReviewerCandidate = {
  user_id?: string | null;
  // The declared source-control username (the repository's default reviewer), when one matched.
  scm_username?: string | null;
  display_name: string;
  primary_email?: string | null;
  score: number;
  available: boolean;
  teams: string[];
  skills: string[];
  approval_roles: string[];
  evidence: WorkReviewerEvidence[];
};

export type WorkReviewerOverride = {
  id: string;
  work_item_id: string;
  change_unit_id?: string | null;
  selected_profile_id?: string | null;
  selected_reviewer: string;
  reason: string;
  evidence: Record<string, unknown>;
  actor_id: string;
  created_at?: string | null;
};

export type WorkReviewerRecommendationPayload = {
  work_item_id: string;
  source_key: string;
  change_unit_count: number;
  recommendations: WorkReviewerCandidate[];
  overrides: WorkReviewerOverride[];
  missing_setup: string[];
};
