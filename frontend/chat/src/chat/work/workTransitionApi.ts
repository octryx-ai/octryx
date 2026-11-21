import { readJson } from "../../admin/utils/adminPanelHelpers";
import type { WorkStateEvent, WorkTransitionPreview } from "./workSyncWorkflowTypes";

// Applying a workflow transition to a Work Item and reading its state events.
// POST /work-items/{id}/transition writes to Jira first when the workflow syncs back in execute mode; a mapped
// transition Jira does not offer from the issue's status is refused with 409 and the offers in the message.

export type WorkTransitionResult = {
  item_id: string;
  work_state: string;
  preview: WorkTransitionPreview;
  event: WorkStateEvent;
};

type TransitionRequest = {
  workflowId: string;
  workItemId: string;
  toState: string;
  reason: string;
  // The item's last synced Jira update: the server refuses when Jira changed since (conflict guard).
  sourceJiraUpdatedAt?: string | null;
};

function conflictGuard(sourceJiraUpdatedAt: string | null | undefined) {
  return sourceJiraUpdatedAt ? { source_jira_updated_at: sourceJiraUpdatedAt } : {};
}

// The preview from the item detail: the server's dry run, with the conflict guard (judge r7).
export async function previewWorkTransition({ workflowId, workItemId, toState, reason, sourceJiraUpdatedAt }: TransitionRequest):
  Promise<{ preview: WorkTransitionPreview; event: WorkStateEvent }> {
  return readJson<{ preview: WorkTransitionPreview; event: WorkStateEvent }>(
    `/api/v1/secure-work/workflows/${encodeURIComponent(workflowId)}/dry-run-transition`,
    {
      method: "POST",
      body: JSON.stringify({
        work_item_id: workItemId, to_state: toState, reason, source: "ui_preview", ...conflictGuard(sourceJiraUpdatedAt),
      }),
    },
  );
}

// The apply sends back the preview's binding (C-7 effects hash and workflow version), so the server applies only
// what was previewed.
export async function applyWorkTransition({
  workflowId,
  workItemId,
  toState,
  reason,
  sourceJiraUpdatedAt,
  binding = {},
}: TransitionRequest & { binding?: { effects_hash?: string; workflow_updated_at?: string } }): Promise<WorkTransitionResult> {
  return readJson<WorkTransitionResult>(`/api/v1/secure-work/work-items/${encodeURIComponent(workItemId)}/transition`, {
    method: "POST",
    body: JSON.stringify({
      workflow_id: workflowId, to_state: toState, reason, source: "ui_apply", ...conflictGuard(sourceJiraUpdatedAt), ...binding,
    }),
  });
}

export async function loadWorkItemStateEvents(workItemId: string): Promise<WorkStateEvent[]> {
  const payload = await readJson<{ items: WorkStateEvent[] }>(
    `/api/v1/secure-work/work-items/${workItemId}/state-events`,
  );
  return payload.items || [];
}
