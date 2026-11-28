export type Answer = { ok: boolean; status: number; body: unknown };

// status 0 = no answer.
export async function call(path: string, method = "GET", body?: unknown): Promise<Answer> {
  try {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let payload: unknown = null;
    try { payload = await response.json(); } catch { /* An answer without JSON keeps its status. */ }
    return { ok: response.ok, status: response.status, body: payload };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

export const workspacePath = (workspaceId: string) => `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`;
