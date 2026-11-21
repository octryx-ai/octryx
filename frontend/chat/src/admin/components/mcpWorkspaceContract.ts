// Request contract of the Workspace-scoped MCP registry
// (backend/app/web/routers/panel_channels.py, schemas MCPServerCreateRequest,
// MCPCatalogInstallRequest and MCPServerUpdateRequest, all extra="forbid").
//
// Every registry call names one Workspace explicitly: listings return the
// platform servers plus that Workspace's servers, and server actions resolve
// the name inside that scope. Registrations created from the admin tab are
// owned by the selected Workspace. Catalog secret fields are bound only as
// Secret References, never as raw values.

export const MCP_PANEL_API = "/admin/chat/api/panel/mcp";

/** Remote transports the backend accepts for custom registrations. */
export const MCP_CUSTOM_TRANSPORTS = ["streamable-http", "sse"] as const;
export type McpCustomTransport = (typeof MCP_CUSTOM_TRANSPORTS)[number];
export const MCP_DEFAULT_CUSTOM_TRANSPORT: McpCustomTransport =
  "streamable-http";

export const MCP_WORKSPACE_OWNER_SCOPE = "workspace";

export type McpWorkspaceOption = { id: string; name: string };

type McpWorkspaceSource = {
  id: string;
  name?: string | null;
  is_active?: boolean | null;
};

type McpCatalogFieldLike = {
  name: string;
  type: string;
  default?: string | null;
};

type McpCatalogPresetLike = { fields?: McpCatalogFieldLike[] | null };

export type McpCatalogValueBody = {
  settings: Record<string, string>;
  secret_refs: Record<string, string>;
};

/** Active projects only: the backend rejects inactive Workspaces with 404. */
export function mcpWorkspaceOptions(
  projects: ReadonlyArray<McpWorkspaceSource> | null | undefined,
): McpWorkspaceOption[] {
  return (projects || [])
    .filter((project) => project.is_active !== false)
    .map((project) => ({
      id: String(project.id || "").trim(),
      name: String(project.name || "").trim(),
    }))
    .filter((project) => project.id)
    .map((project) => ({ id: project.id, name: project.name || project.id }));
}

/**
 * Keep the current selection while it is still listed, else no Workspace.
 * There is deliberately no "first project" fallback: the shared active
 * workspace (chat/useActiveWorkspace) supplies the selection, and an unrelated
 * or temporary Workspace must never be preselected without intent.
 */
export function resolveMcpWorkspaceId(
  options: ReadonlyArray<McpWorkspaceOption>,
  currentId: string | null | undefined,
): string {
  const current = String(currentId || "").trim();
  if (current && options.some((option) => option.id === current)) {
    return current;
  }
  return "";
}

function requireWorkspaceId(workspaceId: string): string {
  const normalized = String(workspaceId || "").trim();
  if (!normalized) {
    throw new Error("Select a Workspace before managing MCP servers.");
  }
  return normalized;
}

function withWorkspace(path: string, workspaceId: string): string {
  const query = new URLSearchParams({
    workspace_id: requireWorkspaceId(workspaceId),
  });
  return `${path}?${query.toString()}`;
}

export function mcpServersListPath(workspaceId: string): string {
  return withWorkspace(`${MCP_PANEL_API}/servers`, workspaceId);
}

export function mcpCatalogListPath(workspaceId: string): string {
  return withWorkspace(`${MCP_PANEL_API}/catalog`, workspaceId);
}

/** Collection path for POST create; ownership travels in the body. */
export const MCP_SERVERS_CREATE_PATH = `${MCP_PANEL_API}/servers`;

export function mcpCatalogInstallPath(slug: string): string {
  return `${MCP_PANEL_API}/catalog/${encodeURIComponent(slug)}/install`;
}

/** Path for PUT/DELETE on one server, or its connect/disconnect action. */
export function mcpServerActionPath(
  serverName: string,
  workspaceId: string,
  action?: "connect" | "disconnect",
): string {
  const base = `${MCP_PANEL_API}/servers/${encodeURIComponent(serverName)}`;
  return withWorkspace(action ? `${base}/${action}` : base, workspaceId);
}

export function isMcpSecretField(field: { type?: string | null }): boolean {
  return (
    String(field.type || "")
      .trim()
      .toLowerCase() === "password"
  );
}

/**
 * Split form values into plain settings and Secret References.
 *
 * Blank secret values are always omitted: on install nothing is bound, on
 * update the stored binding is kept. Blank plain values are omitted on install
 * (the preset default applies) and sent on update so a field can be cleared.
 */
export function splitMcpCatalogValues(
  preset: McpCatalogPresetLike,
  values: Record<string, string>,
  mode: "install" | "update",
): McpCatalogValueBody {
  const settings: Record<string, string> = {};
  const secretRefs: Record<string, string> = {};
  for (const field of preset.fields || []) {
    const value = String(values[field.name] ?? "").trim();
    if (isMcpSecretField(field)) {
      if (value) secretRefs[field.name] = value;
      continue;
    }
    if (value || mode === "update") settings[field.name] = value;
  }
  return { settings, secret_refs: secretRefs };
}

export function buildMcpCatalogInstallBody(args: {
  preset: McpCatalogPresetLike;
  workspaceId: string;
  name: string;
  autoStart: boolean;
  values: Record<string, string>;
}) {
  return {
    owner_scope: MCP_WORKSPACE_OWNER_SCOPE,
    workspace_id: requireWorkspaceId(args.workspaceId),
    name: args.name.trim(),
    auto_start: args.autoStart,
    ...splitMcpCatalogValues(args.preset, args.values, "install"),
  };
}

export function buildMcpCatalogUpdateBody(args: {
  preset: McpCatalogPresetLike;
  autoStart: boolean;
  values: Record<string, string>;
}) {
  return {
    auto_start: args.autoStart,
    ...splitMcpCatalogValues(args.preset, args.values, "update"),
  };
}

export function buildMcpCustomServerBody(args: {
  workspaceId: string;
  name: string;
  transport: string;
  url: string;
  description: string;
  autoStart: boolean;
}) {
  return {
    owner_scope: MCP_WORKSPACE_OWNER_SCOPE,
    workspace_id: requireWorkspaceId(args.workspaceId),
    name: args.name.trim(),
    transport: args.transport,
    url: args.url.trim(),
    description: args.description.trim(),
    auto_start: args.autoStart,
  };
}

/** Edit form seed: stored plain settings (or defaults), secrets left blank. */
export function mcpEditValuesFromSettings(
  preset: McpCatalogPresetLike,
  settings: Record<string, unknown> | null | undefined,
): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of preset.fields || []) {
    if (isMcpSecretField(field)) {
      values[field.name] = "";
      continue;
    }
    const stored = settings?.[field.name];
    values[field.name] =
      stored === undefined || stored === null
        ? String(field.default || "")
        : String(stored);
  }
  return values;
}
