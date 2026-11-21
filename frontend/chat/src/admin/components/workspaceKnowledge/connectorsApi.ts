// Typed client of the Source Sync connectors of one Workspace (/knowledge/connectors).
// A connector reads the Workspace's own Confluence, Jira, ServiceNow or Kubernetes tool connection, or a public
// GitHub repository (or a local snapshot the launcher uploads); it stores no credential.

import { knowledgeBase } from "./workspaceKnowledgeRequest";
import { ConnectorRequestError, notGrantedView, reasonText } from "./connectorReasons";
import type { AccessMode, ConnectionRepositoryConfig, ConnectorConfig, SourceConnector, SyncRun } from "./connectorTypes";

export async function connectorRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...init,
    headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}) },
  });
  if (response.ok) return (await response.json()) as T;
  let detail: unknown = null;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // Keep the status text below.
  }
  // A fixed reason (409/422/400), or a fixed code (403 rest_source_visibility_admin_only).
  if (detail && typeof detail === "object" && ("reason" in detail || "code" in detail)) {
    const { reason, code: fixed, field, connection_id: connectionId, connection_name: connectionName } = detail as {
      reason?: unknown; code?: unknown; field?: unknown; connection_id?: unknown; connection_name?: unknown;
    };
    const code = String(reason ?? fixed);
    const path = typeof field === "string" ? field : null;
    const connection = {
      id: typeof connectionId === "string" && connectionId ? connectionId : null,
      name: typeof connectionName === "string" && connectionName ? connectionName : null,
    };
    const error = new ConnectorRequestError(`Refused${path ? ` (${path})` : ""}: ${reasonText(code)}.`, code, path, response.status, connection);
    const notGranted = notGrantedView(error);
    if (notGranted) throw new ConnectorRequestError(notGranted.text, code, path, response.status, connection);
    throw error;
  }
  const text = typeof detail === "string" && detail ? detail : response.statusText;
  throw new ConnectorRequestError(text || `Request failed (${response.status})`, null, null, response.status);
}

function connectorsBase(workspaceId: string): string {
  return `${knowledgeBase(workspaceId)}/connectors`;
}

function connectorUrl(workspaceId: string, connectorKey: string, suffix = ""): string {
  return `${connectorsBase(workspaceId)}/${encodeURIComponent(connectorKey)}${suffix}`;
}

export type ConnectorDeletion = {
  state: "deleted";
  connector_key: string;
  kind: string;
  retained_sources: number;
  removed_sync_items: number;
  removed_runs: number;
};

export const connectorsApi = {
  list: (workspaceId: string) =>
    // may_author: whether the caller may configure and run connectors (Workspace admin or owner).
    connectorRequest<{ connectors: SourceConnector[]; may_author?: boolean }>(connectorsBase(workspaceId)),
  configure: (workspaceId: string, connectorKey: string, config: ConnectorConfig | ConnectionRepositoryConfig) =>
    connectorRequest<SourceConnector>(connectorUrl(workspaceId, connectorKey), {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  run: (workspaceId: string, connectorKey: string) =>
    connectorRequest<SyncRun>(connectorUrl(workspaceId, connectorKey, "/runs"), { method: "POST" }),
  // Stops the schedule and removes the connector; the sources it already synced stay in the Workspace.
  remove: (workspaceId: string, connectorKey: string) =>
    connectorRequest<ConnectorDeletion>(connectorUrl(workspaceId, connectorKey), { method: "DELETE" }),
  // One source's status (a REST source adds its ACL state).
  get: (workspaceId: string, connectorKey: string) => connectorRequest<SourceConnector>(connectorUrl(workspaceId, connectorKey)),
  // Custom REST dry run: one page of the draft mapped; nothing is saved or ingested (the REST calls are audited).
  sample: (workspaceId: string, connectorKey: string, config: ConnectorConfig) =>
    connectorRequest<Record<string, unknown>>(connectorUrl(workspaceId, connectorKey, "/sample"), {
      method: "POST",
      body: JSON.stringify(config),
    }),
  lastRun: (workspaceId: string, connectorKey: string) =>
    connectorRequest<{ connector_key: string; run: SyncRun | null }>(connectorUrl(workspaceId, connectorKey, "/runs/last")),
  // A Git repository read through a connection: read only, or read & write for agents. Answers the described connector.
  setAccessMode: (workspaceId: string, connectorKey: string, accessMode: AccessMode) =>
    connectorRequest<SourceConnector>(connectorUrl(workspaceId, connectorKey, "/access-mode"), {
      method: "PUT",
      body: JSON.stringify({ access_mode: accessMode }),
    }),
  // A Bitbucket Data Center repository's own Git token: replaced (checked by the server first) or removed. Both answer
  // the described connector, whose git_token says only whether one is configured.
  replaceGitToken: (workspaceId: string, connectorKey: string, gitToken: string) =>
    connectorRequest<SourceConnector>(connectorUrl(workspaceId, connectorKey, "/git-token"), {
      method: "PUT",
      body: JSON.stringify({ git_token: gitToken }),
    }),
  removeGitToken: (workspaceId: string, connectorKey: string) =>
    connectorRequest<SourceConnector>(connectorUrl(workspaceId, connectorKey, "/git-token"), { method: "DELETE" }),
};
