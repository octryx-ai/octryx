import type { AtlassianProduct } from "../connectorsTab/atlassianAuthModes";
import {
  CONNECTION_PRODUCTS,
  isRecord,
  type ConnectionHealth,
  type ConnectionMode,
  type WorkspaceConnection,
} from "./workspaceConnectionTypes";

export function connectionProduct(
  connectorName: string,
): AtlassianProduct | null {
  return (CONNECTION_PRODUCTS as readonly string[]).includes(connectorName)
    ? (connectorName as AtlassianProduct)
    : null;
}

export function connectionUrl(
  projectId: string,
  connectorName: string,
  suffix = "",
): string {
  return `/admin/chat/api/panel/projects/${encodeURIComponent(projectId)}/connectors/${encodeURIComponent(connectorName)}/connection${suffix}`;
}

/** The request body's source for a UI choice. */
export function sourceOf(mode: ConnectionMode): "global" | "workspace" {
  return mode === "own" ? "workspace" : "global";
}

/** The server's answer read strictly; null when it is not a connection (the caller then says so). */
export function parseConnection(payload: unknown): WorkspaceConnection | null {
  if (
    !isRecord(payload) ||
    (payload.source !== "global" && payload.source !== "workspace")
  )
    return null;
  const publicFields = isRecord(payload.fields) ? payload.fields : {};
  const secretStatus: Record<string, boolean> = {};
  if (isRecord(payload.secret_status)) {
    for (const [field, stored] of Object.entries(payload.secret_status))
      secretStatus[field] = stored === true;
  }
  let health: ConnectionHealth | null = null;
  if (isRecord(payload.health)) {
    const status = payload.health.status;
    health = {
      status:
        status === "ok" ? "ok" : status === "error" ? "failing" : "unknown",
      checkedAt:
        typeof payload.health.last_checked === "string"
          ? payload.health.last_checked
          : null,
    };
  }
  // The server always reports both (`workspace_connection_service`: `global.configured`, `global.active`).
  const globalConfigured = isRecord(payload.global) && payload.global.configured === true;
  const globalActive = isRecord(payload.global) && payload.global.active === true;
  // Computed from the stored entry by the server, never from the last test; only an incomplete or disabled own entry has one.
  const incomplete =
    payload.state === "own_incomplete" || payload.state === "own_disabled";
  const stateSummary =
    incomplete &&
    typeof payload.state_summary === "string" &&
    payload.state_summary.trim()
      ? payload.state_summary.trim()
      : null;
  return {
    mode: payload.source === "workspace" ? "own" : "global",
    globalConfigured,
    globalActive,
    publicFields,
    secretStatus,
    health,
    incomplete,
    stateSummary,
  };
}

/** The shape the shared sign-in model reads (tool_name, public_fields, secret_status). */
export function connectionAsConnector(
  connectorName: string,
  connection: WorkspaceConnection | null,
) {
  const own = connection?.mode === "own";
  return {
    tool_name: connectorName,
    configured: own,
    public_fields: own && connection ? connection.publicFields : {},
    secret_status: own && connection ? connection.secretStatus : {},
  };
}

/** The draft an own connection opens with: its stored text fields, never a secret. */
export function connectionDraft(
  connection: WorkspaceConnection | null,
): Record<string, string> {
  if (connection?.mode !== "own") return {};
  const draft: Record<string, string> = {};
  for (const [field, value] of Object.entries(connection.publicFields)) {
    if (typeof value === "string") draft[field] = value;
  }
  return draft;
}

/** True when the Workspace's own connection is saved with a URL and a sign-in method (runtime can use it). */
export function ownConnectionReady(
  product: AtlassianProduct,
  connection: WorkspaceConnection | null,
): boolean {
  if (connection?.mode !== "own" || connection.incomplete) return false;
  const url = connection.publicFields[`${product}_url`];
  const mode = connection.publicFields[`${product}_auth_mode`];
  return (
    typeof url === "string" &&
    url.trim() !== "" &&
    typeof mode === "string" &&
    mode !== ""
  );
}
