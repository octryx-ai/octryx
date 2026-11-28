import type { WorkChangePlanStatus } from "./workChangePlanTypes";

// `work_item` carries only identifying fields, so the detail always loads the full Work Item by id.
export type WorkChangePlanSummaryWorkItem = {
  id: string;
  source_key: string;
  title: string;
  project_id: string | null;
  work_state: string;
  source_url: string | null;
};

export type WorkChangePlanSummary = {
  id: string;
  work_item_id: string;
  version: number;
  status: WorkChangePlanStatus | string;
  title: string;
  workflow_id: string | null;
  supersedes_plan_id: string | null;
  plan_type: string | null;
  open_questions_count: number;
  acceptance_criteria_count: number;
  change_unit_count: number;
  created_by: string;
  created_by_name: string | null;
  decided_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  decided_at: string | null;
  approved_at: string | null;
  work_item: WorkChangePlanSummaryWorkItem;
};

export type WorkChangePlanList = {
  items: WorkChangePlanSummary[];
  next_cursor: string | null;
  status_counts: Record<string, number>;
};

export type WorkChangePlanListQuery = {
  // "review" = the backend's review queue (persisted ready_for_review); never derived here.
  queue?: "review";
  statuses?: string[];
  includeSuperseded?: boolean;
  projectId?: string;
  limit?: number;
  cursor?: string | null;
};
