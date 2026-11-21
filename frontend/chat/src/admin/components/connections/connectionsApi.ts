// The connection endpoints as the page calls them.
// Plain fetch, because the page's state depends on the status: a 404 on the list means the server has no central
// connections yet ("needs configuration", no stand-in data).
import { readWorkspaceLimits, type UnboundToday } from "./boundScopes";
import { fieldErrorsOf } from "./connectionDraft";
import { readConnectionTypes, type ConnectionType } from "./connectionTypes";
import {
  deleteResultText,
  intakeSyncText,
  readConnectionDetail,
  readConnectionList,
  readTestResult,
  type ConnectionDetail,
  type ConnectionRow,
  type TestResult,
  type WorkspaceRef,
} from "./connectionsModel";

export type ListResult =
  | { kind: "ok"; connections: ConnectionRow[] }
  | { kind: "needs_configuration" }
  | { kind: "error"; message: string };
export type SaveResult = { ok: true; detail: ConnectionDetail | null } | { ok: false; field: string; message: string; code: string };

const BASE = "/api/v1/admin/connections";

async function call(path: string, init?: RequestInit): Promise<{ status: number; payload: unknown }> {
  const response = await fetch(path, {
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
  return { status: response.status, payload };
}

/** The connections; with a workspace id only those available in that workspace (?workspace_id=, contract 1.1). */
export async function listConnections(workspaceId = ""): Promise<ListResult> {
  try {
    const { status, payload } = await call(workspaceId ? `${BASE}?workspace_id=${encodeURIComponent(workspaceId)}` : BASE);
    if (status === 404) return { kind: "needs_configuration" };
    if (status < 200 || status >= 300) return { kind: "error", message: "The connections could not be loaded." };
    return { kind: "ok", connections: readConnectionList(payload) };
  } catch {
    return { kind: "error", message: "The connections could not be loaded." };
  }
}

/** The kinds of connection the server knows (its connector descriptors); [] when it cannot say. */
export async function loadConnectionTypes(): Promise<ConnectionType[]> {
  try {
    const { status, payload } = await call("/api/v1/admin/connection-types");
    return status >= 200 && status < 300 ? readConnectionTypes(payload) : [];
  } catch {
    return [];
  }
}

export async function loadConnection(id: string): Promise<ConnectionDetail | null> {
  const { status, payload } = await call(`${BASE}/${encodeURIComponent(id)}`);
  return status >= 200 && status < 300 ? readConnectionDetail(payload) : null;
}

async function save(path: string, method: "PUT" | "POST", body: Record<string, unknown>): Promise<SaveResult> {
  try {
    const { status, payload } = await call(path, { method, body: JSON.stringify(body) });
    if (status >= 200 && status < 300) return { ok: true, detail: readConnectionDetail(payload) };
    return { ok: false, ...fieldErrorsOf(payload) };
  } catch {
    return { ok: false, field: "", message: "The change could not be saved.", code: "" };
  }
}

/** Partial update: fields left out stay as they are. */
export const updateConnection = (id: string, body: Record<string, unknown>) => save(`${BASE}/${encodeURIComponent(id)}`, "PUT", body);
export const createConnection = (body: Record<string, unknown>) => save(BASE, "POST", body);

export async function testConnection(id: string): Promise<TestResult | null> {
  try {
    const { status, payload } = await call(`${BASE}/${encodeURIComponent(id)}/test`, { method: "POST" });
    return status >= 200 && status < 300 ? readTestResult(payload) : null;
  } catch {
    return null;
  }
}

/** Delete: only without active uses; otherwise the answer names them (409 connection_in_use). */
export async function deleteConnection(id: string): Promise<{ ok: boolean; text: string }> {
  try {
    const { status, payload } = await call(`${BASE}/${encodeURIComponent(id)}`, { method: "DELETE" });
    return deleteResultText(status, payload);
  } catch {
    return { ok: false, text: "The connection could not be deleted." };
  }
}

/** Reset: the workspace uses the connection as it is again. */
export async function resetDeviation(workspaceId: string, connectionId: string): Promise<boolean> {
  try {
    const path = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/connections/${encodeURIComponent(connectionId)}/deviation`;
    const { status } = await call(path, { method: "DELETE" });
    return status >= 200 && status < 300;
  } catch {
    return false;
  }
}

/** "Sync now" of one intake (existing endpoint); the answer as one sentence. */
export async function syncIntake(workspaceId: string, intakeId: string): Promise<string> {
  try {
    const path = `/api/v1/secure-work/workspaces/${encodeURIComponent(workspaceId)}/intake/${encodeURIComponent(intakeId)}/sync`;
    const { status, payload } = await call(path, { method: "POST" });
    return intakeSyncText(status, payload);
  } catch {
    return "The sync could not be started.";
  }
}

/** At most this many Workspaces are read for "Today, unbound" (the batch route's limit); more says "each Workspace's list". */
export const MAX_ALLOWLIST_WORKSPACES = 200;

/**
 * Each Workspace's allowed keys of `connector` and the global list, in one request (GET
 * /admin/chat/api/panel/connectors/{connector}/workspace-limits?ids=…; platform admins). one request
 * per Workspace exhausted the API's database pool on Preview. Null when the read fails or there are too many.
 */
export async function loadUnboundToday(workspaces: WorkspaceRef[], connector: string, field: string): Promise<UnboundToday | null> {
  if (!workspaces.length || workspaces.length > MAX_ALLOWLIST_WORKSPACES) return null;
  try {
    const query = workspaces.map((workspace) => `ids=${encodeURIComponent(workspace.id)}`).join("&");
    const { status, payload } = await call(`/admin/chat/api/panel/connectors/${encodeURIComponent(connector)}/workspace-limits?${query}`);
    return status >= 200 && status < 300 ? readWorkspaceLimits(payload, field, workspaces) : null;
  } catch {
    return null;
  }
}
