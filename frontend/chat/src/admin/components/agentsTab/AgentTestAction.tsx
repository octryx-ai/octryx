import { useState } from "react";

import { agentTestChatHref, agentWorkspaceOptions } from "./agentWorkspaceModel";

type AgentTestActionProps = {
  agent: { id: string; projectId?: string | null };
  active: boolean;
  workspaces: { id: string; name: string; is_active?: boolean }[];
  // A run of this agent would be refused (e.g. no published revision in published mode).
  blockedReason?: string;
  onLeave?: () => void;
};

// "Test in chat" opens a new chat with this agent applied and an explicit
// workspace: the agent's own one, or — for a global agent — the one the user
// picks here. Inactive agents cannot be selected in chat, so they cannot be tested.
export function AgentTestAction({ agent, active, workspaces, blockedReason, onLeave }: AgentTestActionProps) {
  const [chosen, setChosen] = useState("");
  const fixed = agent.projectId || "";
  const workspaceId = fixed || chosen;
  const options = agentWorkspaceOptions(workspaces).filter((option) => !option.inactive);

  const fixedWorkspace = workspaces.find((workspace) => workspace.id === fixed);
  const blocked = !active
    ? "Activate the agent first (Edit settings → “Agent is active”)."
    : fixedWorkspace?.is_active === false
      ? `Its workspace “${fixedWorkspace.name}” is inactive. Choose an active workspace in Edit settings.`
      : blockedReason || "";
  if (blocked) {
    return (
      <div className="agent-workspace__test">
        <button type="button" className="admin-panel__action-btn" disabled>Test in chat</button>
        <span className="agent-workspace__hint">{blocked}</span>
      </div>
    );
  }
  return (
    <div className="agent-workspace__test">
      {!fixed ? (
        <label className="agent-workspace__test-scope">
          <span>Test in workspace</span>
          <select value={chosen} onChange={(event) => setChosen(event.target.value)} aria-label="Test in workspace">
            <option value="">Choose a workspace…</option>
            {options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
          </select>
        </label>
      ) : null}
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={!workspaceId}
        onClick={() => {
          onLeave?.();
          window.location.href = agentTestChatHref(agent.id, workspaceId);
        }}
      >
        Test in chat
      </button>
      <span className="agent-workspace__hint">
        {fixed ? "Opens a new chat with this agent in its workspace." : "A global agent can run in any workspace; choose where to test it."}
      </span>
    </div>
  );
}
