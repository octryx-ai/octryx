import { myWorkPath, myWorkStateFrom, type MyWorkState } from "./myWorkModel";

// Reads and stores "You in Jira" (myWorkModel.ts holds the contract). Plain fetch: the state depends on the status.

async function call(workspaceId: string, init?: RequestInit): Promise<MyWorkState> {
  try {
    const response = await fetch(myWorkPath(workspaceId), {
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
      ...init,
    });
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    return myWorkStateFrom(response.status, payload);
  } catch {
    return { kind: "error", message: "Who you are in Jira could not be loaded." };
  }
}

export function loadMyWork(workspaceId: string): Promise<MyWorkState> {
  return call(workspaceId);
}

export function saveMyWork(workspaceId: string, accountId: string): Promise<MyWorkState> {
  return call(workspaceId, { method: "PUT", body: JSON.stringify({ source_type: "jira", account_id: accountId }) });
}

export function clearMyWork(workspaceId: string): Promise<MyWorkState> {
  return call(workspaceId, { method: "DELETE" });
}
