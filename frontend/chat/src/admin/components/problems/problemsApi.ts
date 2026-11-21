import { problemsQuery, readProblems, refusalText, type ProblemFilters, type ProblemList } from "./problemsModel";

// E5 Problems endpoints (backend). Refusals carry {detail: {code, message, field?}}.

// A refusal is a plain Error tagged by name, so the check also holds where `extends Error` is down-levelled.
export type ProblemsRefusal = Error & { status: number; code: string };

function refusal(status: number, code: string, message: string): ProblemsRefusal {
  return Object.assign(new Error(message), { name: "ProblemsRefusal", status, code });
}

export function isRefusal(error: unknown): error is ProblemsRefusal {
  return error instanceof Error && error.name === "ProblemsRefusal";
}

async function call(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : null;
    const code = detail && typeof detail === "object" && typeof (detail as { code?: unknown }).code === "string"
      ? String((detail as { code: string }).code) : "";
    const message = typeof detail === "string" ? detail
      : detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string"
        ? String((detail as { message: string }).message) : "";
    throw refusal(response.status, code, refusalText(response.status, code, message));
  }
  return payload;
}

/** Admin view: platform admins see everything, Workspace admins only their Workspaces. */
export async function loadAdminProblems(filters: ProblemFilters): Promise<ProblemList> {
  return readProblems(await call(`/api/v1/admin/problems${problemsQuery(filters)}`));
}

/** One Workspace, for its members (the future Workspace page). */
export async function loadWorkspaceProblems(workspaceId: string, kind?: string): Promise<ProblemList> {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return readProblems(await call(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/problems${query}`));
}

/** Hide one problem for the caller until it happens again. */
export async function acknowledgeProblem(key: string): Promise<void> {
  await call(`/api/v1/admin/problems/${encodeURIComponent(key)}/acknowledge`, { method: "POST" });
}
