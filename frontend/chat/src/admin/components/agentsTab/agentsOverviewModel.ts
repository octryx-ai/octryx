// The Agents list of Agents & workflows: Workspace agents and built-ins, their capability ceiling,
// default workflow, scope, use in the last 30 days and status. Pure; the page renders it.
import type { BadgeKind } from "../agentsWorkflows/awBadges";

export type OverviewBuiltin = {
  key: string;
  name: string;
  description: string;
  capability_ceiling: string;
  default_workflow_key: string;
  row: boolean;
};

export type AgentsOverview = {
  builtins: OverviewBuiltin[];
  usageWindowDays: number;
  usage: Record<string, number>;
};

export type OverviewAgent = {
  id: string;
  name: string;
  description?: string;
  goal?: string;
  projectId?: string;
  builtinKey?: string;
  capabilityCeiling?: string;
  defaultWorkflowKey?: string;
  isActive?: boolean;
  is_active?: boolean;
};

export type AgentRow = {
  id: string | null;
  name: string;
  description: string;
  ceiling: string;
  defaultWorkflow: string;
  scope: string;
  used: number | null;
  status: [string, BadgeKind];
  builtin: boolean;
};

export const EMPTY_OVERVIEW: AgentsOverview = { builtins: [], usageWindowDays: 30, usage: {} };

export function readAgentsOverview(raw: unknown): AgentsOverview {
  const body = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const builtins = Array.isArray(body.builtins) ? (body.builtins as OverviewBuiltin[]) : [];
  const usage = body.usage && typeof body.usage === "object" ? (body.usage as Record<string, number>) : {};
  return { builtins, usageWindowDays: Number(body.usage_window_days) || 30, usage };
}

export function agentRows(
  agents: OverviewAgent[],
  overview: AgentsOverview,
  projects: { id: string; name: string }[],
): AgentRow[] {
  const projectName = new Map(projects.map((project) => [project.id, project.name]));
  const listedOnly = overview.builtins
    .filter((builtin) => !builtin.row)
    .map<AgentRow>((builtin) => ({
      id: null,
      name: builtin.name,
      description: builtin.description,
      ceiling: builtin.capability_ceiling,
      defaultWorkflow: builtin.default_workflow_key || "Automatic",
      scope: "Built-in",
      used: null,
      status: ["Built-in", "neutral"],
      builtin: true,
    }));
  const rows = agents.map<AgentRow>((agent) => {
    const active = Boolean(agent.isActive ?? agent.is_active);
    const builtin = Boolean(agent.builtinKey);
    return {
      id: agent.id,
      name: agent.name,
      description: String(agent.description || agent.goal || "").replace(/\s+/g, " ").trim(),
      ceiling: agent.capabilityCeiling || "read_only",
      defaultWorkflow: agent.defaultWorkflowKey || "Automatic",
      scope: builtin ? "Built-in" : agent.projectId ? projectName.get(agent.projectId) ?? "Unknown Workspace" : "Global",
      used: overview.usage[agent.id] ?? 0,
      status: builtin ? ["Built-in", "neutral"] : active ? ["Active", "active"] : ["Draft", "attention"],
      builtin,
    };
  });
  const builtinRows = rows.filter((row) => row.builtin);
  const workspaceRows = rows.filter((row) => !row.builtin);
  return [...listedOnly.slice(0, 1), ...builtinRows, ...listedOnly.slice(1), ...workspaceRows];
}

export function filterAgentRows(rows: AgentRow[], query: string, ceiling: string): AgentRow[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => {
    if (ceiling && row.ceiling !== ceiling) return false;
    if (!needle) return true;
    return [row.name, row.description, row.defaultWorkflow, row.scope].some((value) =>
      value.toLowerCase().includes(needle),
    );
  });
}
