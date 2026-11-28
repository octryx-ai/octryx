import { readJson } from "../../admin/utils/adminPanelHelpers";

export function loadAgentPresence(projectId: string): Promise<unknown> {
  return readJson<unknown>(`/api/v1/agent-gateway/presence?project_id=${encodeURIComponent(projectId)}`);
}

export function removeAgentPresence(entryId: string, projectId: string): Promise<unknown> {
  return readJson<unknown>(
    `/api/v1/agent-gateway/presence/${encodeURIComponent(entryId)}?project_id=${encodeURIComponent(projectId)}`,
    { method: "DELETE" },
  );
}
