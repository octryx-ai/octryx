// The open agent's readiness (status, mode and its permissions, workspace scope) and which agent is open.
import { capabilityLabel, type AgentModeLike } from "../../hooks/useAdminAgentForms.defaults";
import { toolSurfaceFromAgent, toolSurfaceLabel } from "./agentToolSurface";

export type AgentListAgent = {
  id: string;
  name: string;
  description?: string;
  goal?: string;
  agentType?: string;
  agent_type?: string;
  projectId?: string;
  groupName?: string;
  isActive?: boolean;
  is_active?: boolean;
  steps?: unknown[];
  toolSurface?: unknown;
};

export type AgentReadiness = {
  active: boolean;
  modeKey: string;
  modeName: string;
  permissions: string;
  workspace: string;
  stepCount: number;
};

type ProjectRef = { id: string; name: string };

export function isAgentActive(agent: AgentListAgent): boolean {
  return Boolean(agent.isActive ?? agent.is_active);
}

export function agentReadiness(
  agent: AgentListAgent,
  modes: AgentModeLike[],
  projects: ProjectRef[],
): AgentReadiness {
  const modeKey = agent.agentType || agent.agent_type || "";
  const mode = modes.find((item) => item.key === modeKey);
  const project = agent.projectId
    ? projects.find((item) => item.id === agent.projectId)
    : undefined;
  return {
    active: isAgentActive(agent),
    modeKey,
    modeName: mode?.name || modeKey || "No mode",
    // A text-only (or unknown) tool setting overrides what the mode would allow.
    permissions: toolSurfaceFromAgent(agent) === "governed" ? capabilityLabel(mode?.capability_type) : toolSurfaceLabel(toolSurfaceFromAgent(agent)),
    workspace: agent.projectId ? (project?.name ?? "Unknown workspace") : "Global",
    stepCount: Array.isArray(agent.steps) ? agent.steps.length : 0,
  };
}

// The agent whose page is open. A selected id only counts while that agent is
// in the loaded list, so a stale selection shows the list and its header.
export function selectedListAgent<T extends AgentListAgent>(agents: unknown, selectedId: unknown): T | undefined {
  if (!Array.isArray(agents) || typeof selectedId !== "string" || !selectedId) return undefined;
  return (agents as T[]).find((agent) => agent?.id === selectedId);
}
