import { readJson } from "../../admin/utils/adminPanelHelpers";
import type { WorkItem } from "./workItemTypes";
import type { WorkChangePlanList, WorkChangePlanListQuery } from "./workPlanListTypes";

export const PLAN_LIST_PAGE_SIZE = 50;

export function changePlanListUrl(query: WorkChangePlanListQuery): string {
  const params = new URLSearchParams();
  if (query.queue) params.set("queue", query.queue);
  for (const status of query.statuses ?? []) params.append("status", status);
  if (query.includeSuperseded !== undefined) params.set("include_superseded", String(query.includeSuperseded));
  if (query.projectId) params.set("project_id", query.projectId);
  params.set("limit", String(query.limit ?? PLAN_LIST_PAGE_SIZE));
  if (query.cursor) params.set("cursor", query.cursor);
  return `/api/v1/secure-work/change-plans?${params.toString()}`;
}

export async function loadChangePlanSummaries(query: WorkChangePlanListQuery): Promise<WorkChangePlanList> {
  const payload = await readJson<WorkChangePlanList>(changePlanListUrl(query));
  return {
    items: payload.items || [],
    next_cursor: payload.next_cursor || null,
    status_counts: payload.status_counts || {},
  };
}

// The full Work Item (same shape as a `GET /work-items` entry), scoped by workspace access; used
// when the item is not among the loaded Work Items (for example outside the first 1000).
export async function loadWorkItem(workItemId: string): Promise<WorkItem> {
  return readJson<WorkItem>(`/api/v1/secure-work/work-items/${encodeURIComponent(workItemId)}`);
}
