import { useEffect, useMemo, useRef } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { AgentWorkspacePage } from "./AgentWorkspacePage";
import { readAgentIdFromSearch, writeAgentIdToUrl } from "../../agentLinks";
import { agentReadiness, selectedListAgent, type AgentListAgent } from "./agentListModel";

type AgentListPanelProps = {
  ctx: Record<string, unknown>;
};

// The open agent's one canonical page (settings, steps, test, used by); "Edit settings" opens the settings
// drawer. ``?agent_id=`` opens an agent directly (links from workflows).
export function AgentListPanel({ ctx }: AgentListPanelProps) {
  const {
    agentBuilderMeta,
    availableAgentModes,
    handleDeleteAgent,
    handleOpenAgentForm,
    onClose,
    panelAgents,
    projects,
    selectedAgentPanelId,
    setSelectedAgentPanelId,
  } = ctx as Record<string, any>;
  const { openAdminTab } = useAdminNavigation();
  const agents: AgentListAgent[] = useMemo(() => (Array.isArray(panelAgents) ? panelAgents : []), [panelAgents]);
  const modes = Array.isArray(agentBuilderMeta?.agent_modes)
    ? agentBuilderMeta.agent_modes
    : Array.isArray(availableAgentModes)
      ? availableAgentModes
      : [];
  const projectOptions = Array.isArray(agentBuilderMeta?.projects)
    ? agentBuilderMeta.projects
    : Array.isArray(projects)
      ? projects
      : [];
  const selected = selectedListAgent<AgentListAgent>(agents, selectedAgentPanelId);

  // Canonical agent destination: `?agent_id=` opens that agent's page
  // (links from workflows), and the open
  // page is reflected in the URL so reload and back keep it.
  const requestedAgentId = useRef(readAgentIdFromSearch(window.location.search));
  useEffect(() => {
    const wanted = requestedAgentId.current;
    if (!wanted || !agents.some((agent) => agent.id === wanted)) return;
    requestedAgentId.current = "";
    setSelectedAgentPanelId(wanted);
  }, [agents, setSelectedAgentPanelId]);
  useEffect(() => {
    if (requestedAgentId.current) return;
    writeAgentIdToUrl(selectedAgentPanelId || null);
  }, [selectedAgentPanelId]);

  // The edit drawer opens over the agent page and returns to it after saving.
  const editAgent = (agent: AgentListAgent) => handleOpenAgentForm(agent);

  if (selected) {
    return (
      <AgentWorkspacePage
        agent={selected}
        ctx={ctx}
        readiness={agentReadiness(selected, modes, projectOptions)}
        workspaces={projectOptions}
        onBack={() => setSelectedAgentPanelId(null)}
        onEdit={() => editAgent(selected)}
        onDelete={() => void handleDeleteAgent(selected)}
        onLeave={onClose}
      />
    );
  }

  // The list itself is AgentsOverviewPage; this panel only shows the open agent's page.
  return null;
}
