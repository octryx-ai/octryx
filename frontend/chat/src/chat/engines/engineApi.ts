import { readJson } from "../../admin/utils/adminPanelHelpers";

// Coding engine settings (backend); answers are read by engineModel.

export type SaveResult = { ok: boolean; status: number; body: unknown };

const PLATFORM_PATH = "/api/v1/admin/agent-engine";
const workspacePath = (projectId: string) => `/api/v1/workspaces/${encodeURIComponent(projectId)}/agent-gateway/engines`;

/** A PUT that keeps a refusal's body: a 422 names the refused field and the card shows it there. */
async function put(path: string, body: unknown): Promise<SaveResult> {
  const response = await fetch(path, {
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

export const loadPlatformEngine = () => readJson<unknown>(PLATFORM_PATH);
export const savePlatformEngine = (body: { default: string }) => put(PLATFORM_PATH, body);

export const loadWorkspaceEngines = (projectId: string) => readJson<unknown>(workspacePath(projectId));
export const saveWorkspaceEngines = (projectId: string, body: { allowed: string[]; default: string | null }) =>
  put(workspacePath(projectId), body);
export const saveOwnEngine = (projectId: string, body: { engine: string | null }) => put(`${workspacePath(projectId)}/me`, body);
