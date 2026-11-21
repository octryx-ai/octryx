import { AgentFormPanel } from "./agentsTab/AgentFormPanel";
import { AgentListPanel } from "./agentsTab/AgentListPanel";
import { AgentsOverviewPage } from "./agentsTab/AgentsOverviewPage";
import { selectedListAgent } from "./agentsTab/agentListModel";
import "./governedRegistry/governedRegistry.css";
import "./agentsTab/agents.css";

type AdminAgentsTabProps = {
  ctx: Record<string, unknown>;
};

// Agents & workflows → Agents: the list of Workspace agents and built-ins, or one agent's page.
export function AdminAgentsTab({ ctx }: AdminAgentsTabProps) {
  const agentPageOpen = Boolean(selectedListAgent(ctx.panelAgents, ctx.selectedAgentPanelId));
  return (
    <div className="agents-tab">
      {agentPageOpen ? <AgentListPanel ctx={ctx} /> : <AgentsOverviewPage ctx={ctx} />}
      <AgentFormPanel ctx={ctx} />
    </div>
  );
}
