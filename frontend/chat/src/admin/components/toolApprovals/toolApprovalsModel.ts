// Settings → Security → Tool & approval policies. Pure: reads
// `/api/v1/admin/tool-approvals` (backend services/tool_approval/policy.py) and words the rules.

// `unattended_allowed_tools`: tools a run no person started may use to write without an approval; the platform
// default's alone (a Workspace never stores one).
export type ApprovalPolicy = {
  require_for_risks: string[]; require_for_tools: string[]; exempt_tools: string[]; unattended_allowed_tools: string[];
};
export type WorkspaceApproval = { id: string; name: string; mode: "inherit" | "add"; own: ApprovalPolicy; effective: Partial<ApprovalPolicy> };
export type ToolInfo = { name: string; risk: string };
export type McpOverview = { servers: string[]; workspaces: { id: string; name: string; servers: Record<string, boolean> }[] };
export type ToolApprovals = { defaults: ApprovalPolicy; risks: string[]; tools: ToolInfo[]; workspaces: WorkspaceApproval[]; mcp: McpOverview };

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const strings = (value: unknown) => (Array.isArray(value) ? value.map((item) => String(item)) : []);
const text = (value: unknown) => (typeof value === "string" ? value : "");

export const EMPTY_POLICY: ApprovalPolicy = { require_for_risks: [], require_for_tools: [], exempt_tools: [], unattended_allowed_tools: [] };

export function readPolicy(value: unknown): ApprovalPolicy {
  const record = isRecord(value) ? value : {};
  return {
    require_for_risks: strings(record.require_for_risks), require_for_tools: strings(record.require_for_tools),
    exempt_tools: strings(record.exempt_tools), unattended_allowed_tools: strings(record.unattended_allowed_tools),
  };
}

export function readToolApprovals(payload: unknown): ToolApprovals | null {
  if (!isRecord(payload) || !isRecord(payload.default)) return null;
  const mcp = isRecord(payload.mcp) ? payload.mcp : {};
  return {
    defaults: readPolicy(payload.default),
    risks: strings(payload.risks),
    tools: Array.isArray(payload.tools) ? payload.tools.filter(isRecord).map((tool) => ({ name: text(tool.name), risk: text(tool.risk) })) : [],
    workspaces: Array.isArray(payload.workspaces) ? payload.workspaces.filter(isRecord).map((row) => ({
      id: text(row.id), name: text(row.name), mode: row.mode === "add" ? "add" : "inherit", own: readPolicy(row.own),
      effective: readPolicy(row.effective),
    })) : [],
    mcp: {
      servers: strings(mcp.servers),
      workspaces: Array.isArray(mcp.workspaces) ? mcp.workspaces.filter(isRecord).map((row) => ({
        id: text(row.id), name: text(row.name),
        servers: isRecord(row.servers) ? Object.fromEntries(Object.entries(row.servers).map(([key, value]) => [key, value === true])) : {},
      })) : [],
    },
  };
}

/** The PUT body of a Workspace's approvals: never `unattended_allowed_tools` (the platform default's alone). */
export function workspaceApprovalBody(mode: "inherit" | "add", policy: ApprovalPolicy): Record<string, unknown> {
  if (mode === "inherit") return { mode };
  return { mode, require_for_risks: policy.require_for_risks, require_for_tools: policy.require_for_tools, exempt_tools: policy.exempt_tools };
}

/** A tool name in words: `create_jira_issue` → "Create jira issue"; MCP names keep their server. */
export function toolLabel(name: string): string {
  if (name.startsWith("mcp__")) return name.replace(/^mcp__/, "MCP ").replace(/__/g, " · ");
  const words = name.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : name;
}

export const RISK_LABEL: Record<string, string> = { read: "Read", write: "Write", admin: "Admin", unknown: "Unknown" };

export function policySummary(policy: ApprovalPolicy): string {
  const parts: string[] = [];
  if (policy.require_for_risks.length) parts.push(`${policy.require_for_risks.map((risk) => RISK_LABEL[risk] ?? risk).join(", ")} risk`);
  if (policy.require_for_tools.length) parts.push(`${policy.require_for_tools.length} ${policy.require_for_tools.length === 1 ? "tool" : "tools"}`);
  return parts.length ? parts.join(", plus ") : "Nothing";
}

export function workspaceSummary(row: WorkspaceApproval): string {
  if (row.mode === "inherit") return "Platform default";
  const added = row.own.require_for_tools.length + row.own.require_for_risks.length;
  return added ? `Default + ${row.own.require_for_tools.map(toolLabel).concat(row.own.require_for_risks.map((risk) => `${RISK_LABEL[risk] ?? risk} risk`)).join(", ")}` : "Platform default";
}
