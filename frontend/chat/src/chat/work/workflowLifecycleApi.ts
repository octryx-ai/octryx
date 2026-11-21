import { readJson } from "../../admin/utils/adminPanelHelpers";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";

// The workflow lifecycle API (api/routes/secure_work_workflows.py): update (partial), deactivate, activate.
// A refusal keeps the server's text: 422 `workflow_state_unknown` with its message, 409 and 403 as answered.
// r8: every change sends the workflow's `updated_at` as loaded, so the server refuses a change to a newer version
// (409, expected code `workflow_stale`) instead of overwriting it.

const version = (updatedAt: string | null | undefined) => (updatedAt ? { updated_at: updatedAt } : {});

export async function updateWorkflow(
  workflowId: string,
  payload: Partial<Pick<WorkWorkflowDefinition, "name" | "description" | "states" | "mappings" | "sync_policy" | "is_default">>,
  updatedAt?: string | null,
): Promise<WorkWorkflowDefinition> {
  return readJson<WorkWorkflowDefinition>(`/api/v1/secure-work/workflows/${encodeURIComponent(workflowId)}`, {
    method: "PUT",
    body: JSON.stringify({ ...payload, ...version(updatedAt) }),
  });
}

export async function setWorkflowActive(
  workflowId: string,
  active: boolean,
  updatedAt?: string | null,
): Promise<WorkWorkflowDefinition> {
  return readJson<WorkWorkflowDefinition>(
    `/api/v1/secure-work/workflows/${encodeURIComponent(workflowId)}/${active ? "activate" : "deactivate"}`,
    { method: "POST", body: JSON.stringify(version(updatedAt)) },
  );
}
