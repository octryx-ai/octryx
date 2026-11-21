import { readJson } from "../../admin/utils/adminPanelHelpers";

// GET /api/v1/agent-gateway/presence?project_id= (contract item 5). The answer is parsed by
// agentPresenceModel.readPresence; refusals keep their HTTP status on the error (readJson).
export function loadAgentPresence(projectId: string): Promise<unknown> {
  return readJson<unknown>(`/api/v1/agent-gateway/presence?project_id=${encodeURIComponent(projectId)}`);
}

// DELETE /api/v1/agent-gateway/presence/{entry_id}?project_id= -> {state: "removed", id, sessions}: one person's
// device leaves the list (newer servers; entries keep 7 days otherwise).
export function removeAgentPresence(entryId: string, projectId: string): Promise<unknown> {
  return readJson<unknown>(
    `/api/v1/agent-gateway/presence/${encodeURIComponent(entryId)}?project_id=${encodeURIComponent(projectId)}`,
    { method: "DELETE" },
  );
}
