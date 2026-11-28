export const MCP_ALLOW_API = "/api/v1/admin";

export type ServerStatus = {
  serverId: string; name: string; connected: boolean; allowedWorkspaces: number; toolsVisible: boolean; toolCount: number;
};
export type AllowWorkspace = { workspaceId: string; name: string; allowed: boolean; tools: string[] | null };
export type ServerAllow = { serverId: string; name: string; connected: boolean; tools: string[]; workspaces: AllowWorkspace[] };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown) => (typeof value === "string" ? value : "");
const list = (value: unknown) => (Array.isArray(value) ? value.filter(isRecord) : []);
const names = (value: unknown) => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : null);

export function readStatus(payload: unknown): Map<string, ServerStatus> {
  const body = isRecord(payload) ? payload : {};
  return new Map(list(body.servers).map((row) => [str(row.server_id), {
    serverId: str(row.server_id), name: str(row.name), connected: row.connected === true,
    allowedWorkspaces: typeof row.allowed_workspaces === "number" ? row.allowed_workspaces : 0,
    toolsVisible: row.tools_visible === true, toolCount: typeof row.tool_count === "number" ? row.tool_count : 0,
  }]));
}

export function readAllow(payload: unknown): ServerAllow {
  const body = isRecord(payload) ? payload : {};
  return {
    serverId: str(body.server_id), name: str(body.name), connected: body.connected === true, tools: names(body.tools) ?? [],
    workspaces: list(body.workspaces).map((row) => ({
      workspaceId: str(row.workspace_id), name: str(row.name), allowed: row.allowed === true, tools: names(row.tools),
    })),
  };
}

export type PipelineStep = { label: string; done: boolean };

export function pipeline(status: ServerStatus | undefined): PipelineStep[] {
  const allowed = status?.allowedWorkspaces ?? 0;
  return [
    { label: "Registered", done: true },
    { label: "Connected", done: Boolean(status?.connected) },
    { label: allowed ? `Allowed in ${allowed} ${allowed === 1 ? "Workspace" : "Workspaces"}` : "Not allowed in any Workspace",
      done: allowed > 0 },
    { label: "Tools visible to agents", done: Boolean(status?.toolsVisible) },
  ];
}

export const inUse = (status: ServerStatus | undefined) => Boolean(status && status.allowedWorkspaces > 0);

export function allowBody(selectedWorkspaces: string[], allTools: boolean, tools: string[]): { body?: Record<string, unknown>; error?: string } {
  if (!allTools && !tools.length) return { error: "Select at least one tool, or expose all tools." };
  return { body: { workspace_ids: [...selectedWorkspaces].sort(), tools: allTools ? null : [...tools].sort() } };
}

export function initialTools(allow: ServerAllow): { allTools: boolean; tools: string[] } {
  const selected = allow.workspaces.find((row) => row.allowed && row.tools)?.tools;
  return selected ? { allTools: false, tools: selected } : { allTools: true, tools: [] };
}

const CODES: Record<string, string> = {
  mcp_tools_invalid: "select at least one tool",
  mcp_server_owned_by_another_workspace: "this server belongs to another Workspace",
  mcp_workspace_unknown: "a Workspace no longer exists",
  mcp_server_unknown: "the server no longer exists",
};

export function allowErrorText(error: unknown): string {
  const record = isRecord(error) ? error : {};
  const code = str(record.code) || (isRecord(record.detail) ? str(record.detail.code) : "");
  return `Not saved: ${CODES[code] ?? "the change was refused"}.`;
}
