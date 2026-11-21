// Work items as imported from a tracker, with comments, lifecycle and automation eligibility.
import type { RunTaskItem } from "../workflowRun/workflowRunTypes";
import type { WorkChangeUnit, WorkPullRequest } from "./workPullRequestTypes";

export type WorkItem = {
  id: string;
  project_id?: string | null;
  sync_config_id?: string | null;
  source_type: string;
  source_instance: string;
  source_id?: string | null;
  source_project_key?: string | null;
  source_key: string;
  source_url?: string | null;
  title: string;
  description?: string;
  issue_type?: string | null;
  source_status?: string | null;
  priority?: string | null;
  assignee?: string | null;
  reporter?: string | null;
  watchers?: string[];
  // B-3 (additive): Jira display names beside the ids above; null when unknown.
  assignee_display?: string | null;
  reporter_display?: string | null;
  watchers_display?: { id: string; display: string | null }[];
  // Read-only from Jira: the last comments, oldest first, plain text.
  comments?: WorkItemComment[];
  comments_total?: number | null;
  // B-2 (additive): how work_state was mapped from the Jira status.
  status_mapping?: { source?: string | null; category?: string | null } | null;
  labels?: string[];
  components?: string[];
  fix_versions?: string[];
  // {id, name, state, goal} / {id, name}, or null for none ({} reads as none too).
  sprint?: Record<string, unknown> | null;
  board?: Record<string, unknown> | null;
  parent_key?: string | null;
  epic_key?: string | null;
  /** The tasks inside the item, each with its status, kept across the item's runs (backend task_status). */
  task_list?: RunTaskItem[];
  linked_issues?: unknown[];
  source_fields?: Record<string, unknown>;
  automation_eligibility?: WorkAutomationEligibility;
  work_state: string;
  sync_state: string;
  source_created_at?: string | null;
  last_source_updated_at?: string | null;
  imported_at?: string | null;
  synced_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type WorkItemComment = {
  id: string;
  author?: string | null;
  author_display?: string | null;
  created?: string | null;
  body?: string | null;
  url?: string | null;
};

export type WorkLifecycleAgentSession = {
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

export type WorkLifecycleBranch = {
  change_unit_id: string;
  repository_name: string;
  branch_name: string;
  status: string;
  repository_url?: string | null;
  branch_url?: string | null;
  pull_request_id?: string | null;
  pull_request_url?: string | null;
};

export type WorkItemLifecycle = {
  work_item: WorkItem;
  links: {
    work_url: string;
    coding_url: string;
    jira_url?: string | null;
    active_chat_url?: string | null;
  };
  agent_sessions: WorkLifecycleAgentSession[];
  active_agent_session?: WorkLifecycleAgentSession | null;
  branches: WorkLifecycleBranch[];
  pull_requests: WorkPullRequest[];
  change_units: WorkChangeUnit[];
};

export type WorkAutomationEligibility = {
  requested: boolean;
  can_start: boolean;
  mode: string;
  trigger_label: string;
  trigger_labels: string[];
  matched_labels: string[];
  blocking_reasons: string[];
  review_reasons: string[];
  reason_codes: string[];
  policy_source: string;
};
