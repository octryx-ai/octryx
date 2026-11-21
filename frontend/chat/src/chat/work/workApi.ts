// Work API calls for work items, workflows and repository profiles.
import { readJson } from "../../admin/utils/adminPanelHelpers";
import type { WorkItem, WorkItemLifecycle } from "./workItemTypes";
import type { WorkRepositoryProfile } from "./workCodingPipelineTypes";
import type { WorkStateEvent, WorkTransitionPreview, WorkWorkflowDefinition } from "./workSyncWorkflowTypes";

// The list is lean and paged ({items, total, limit, offset, next_offset}); description, comments, watchers,
// components, linked issues and source_fields come from the item itself (workPlanListApi.loadWorkItem). A page without
// next_offset ends the loop.
export type WorkItemsPage = { items: WorkItem[]; total: number | null; nextOffset: number | null };

export const WORK_ITEMS_PAGE_SIZE = 200;

export async function loadWorkItemsPage(offset = 0, limit = WORK_ITEMS_PAGE_SIZE, projectId = ""): Promise<WorkItemsPage> {
  const scope = projectId ? `&project_id=${encodeURIComponent(projectId)}` : "";
  const payload = await readJson<{ items?: WorkItem[]; total?: number; next_offset?: number | null }>(
    `/api/v1/secure-work/work-items?limit=${limit}&offset=${offset}${scope}`,
  );
  const items = payload.items || [];
  const next = typeof payload.next_offset === "number" && payload.next_offset > offset ? payload.next_offset : null;
  return { items, total: typeof payload.total === "number" ? payload.total : null, nextOffset: next };
}

/**
 * Every item up to `limit`; the filters stay in the browser because they read list fields only. The first page tells
 * the total, so the remaining pages are requested together instead of one after another (perf step 1: ~950 items
 * were five sequential round trips). They are joined in offset order and end, at the first empty page or
 * at the page without a next offset. A server that sends no total is paged through next_offset one by one.
 */
export async function loadWorkItems(limit = 1000, projectId = ""): Promise<WorkItem[]> {
  const first = await loadWorkItemsPage(0, Math.min(WORK_ITEMS_PAGE_SIZE, limit), projectId);
  const items: WorkItem[] = [...first.items];
  if (!first.items.length || first.nextOffset === null || items.length >= limit) return items;
  if (first.total !== null) {
    const start = first.nextOffset;
    const end = Math.min(first.total, start + limit - items.length);
    // The server's own page size (it may cap the limit), so no offset falls between two pages.
    const step = Math.min(WORK_ITEMS_PAGE_SIZE, start);
    const offsets: number[] = [];
    for (let offset = start; offset < end; offset += step) offsets.push(offset);
    const pages = await Promise.all(offsets.map((offset) =>
      loadWorkItemsPage(offset, Math.min(step, end - offset), projectId)));
    for (const page of pages) {
      items.push(...page.items);
      if (!page.items.length || page.nextOffset === null) break;
    }
    return items;
  }
  let offset: number | null = first.nextOffset;
  while (offset !== null && items.length < limit) {
    const page = await loadWorkItemsPage(offset, Math.min(WORK_ITEMS_PAGE_SIZE, limit - items.length), projectId);
    items.push(...page.items);
    if (!page.items.length) break;
    offset = page.nextOffset;
  }
  return items;
}

export async function loadWorkItemLifecycle(workItemId: string): Promise<WorkItemLifecycle> {
  return readJson<WorkItemLifecycle>(`/api/v1/secure-work/work-items/${workItemId}/lifecycle`);
}

export async function loadWorkflows(): Promise<WorkWorkflowDefinition[]> {
  const payload = await readJson<{ items: WorkWorkflowDefinition[] }>(
    "/api/v1/secure-work/workflows?include_inactive=true",
  );
  return payload.items || [];
}

export async function createWorkWorkflow(payload: Record<string, unknown>): Promise<WorkWorkflowDefinition> {
  return readJson<WorkWorkflowDefinition>("/api/v1/secure-work/workflows", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function dryRunWorkTransition({
  workflowId,
  workItemId,
  toState,
  reason,
}: {
  workflowId: string;
  workItemId: string;
  toState: string;
  reason: string;
}): Promise<{ preview: WorkTransitionPreview; event: WorkStateEvent }> {
  return readJson<{ preview: WorkTransitionPreview; event: WorkStateEvent }>(
    `/api/v1/secure-work/workflows/${workflowId}/dry-run-transition`,
    {
      method: "POST",
      body: JSON.stringify({
        work_item_id: workItemId,
        to_state: toState,
        reason,
        source: "ui_dry_run",
      }),
    },
  );
}

export async function loadRepositoryProfiles(): Promise<WorkRepositoryProfile[]> {
  const payload = await readJson<{ items: WorkRepositoryProfile[] }>(
    "/api/v1/secure-work/repository-profiles?include_inactive=true",
  );
  return payload.items || [];
}

