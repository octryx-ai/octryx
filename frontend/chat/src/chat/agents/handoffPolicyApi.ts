import { readJson } from "../../admin/utils/adminPanelHelpers";

// The Workspace handoff policy routes (freeze 3b); answers are read by handoffPolicyModel.

const path = (projectId: string) => `/api/v1/workspaces/${encodeURIComponent(projectId)}/agent-gateway/handoff-policy`;

export function loadHandoffPolicy(projectId: string): Promise<unknown> {
  return readJson<unknown>(path(projectId));
}

/**
 * Saves the policy. Unlike readJson it keeps a refusal's body, because a 422 lists every refused field
 * (`{detail: {errors: [{code, field}]}}`) and the card names them.
 */
export async function saveHandoffPolicy(projectId: string, body: Record<string, unknown>): Promise<{ ok: boolean; status: number; body: unknown }> {
  const response = await fetch(path(projectId), {
    method: "PUT",
    credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // An answer without JSON keeps its status only.
  }
  return { ok: response.ok, status: response.status, body: payload };
}
