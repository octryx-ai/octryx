import {
  TEXT_ONLY_AGENT_HINT,
  agentAvailabilityNotice,
  chatStartersFor,
  knowledgeDocumentsHref,
  workspaceHint,
} from "./chatOnboarding";
import type {
  ChatAgentAvailability,
  ChatToolSurface,
} from "./chatAgentGuidance";

export function EmptyState({
  projectName,
  projectId,
  agentName,
  agentAvailability = "unknown",
  toolSurface = "unknown",
  onUseStarter,
}: {
  runtimeLabel?: string;
  projectName: string;
  projectId?: string;
  agentName?: string;
  // Of the agent shown for the next message; "unknown" never advertises a capability.
  agentAvailability?: ChatAgentAvailability | "unknown";
  toolSurface?: ChatToolSurface;
  onUseStarter?: (prompt: string) => void;
}) {
  const notice = agentAvailabilityNotice(agentAvailability, agentName ?? "");
  const textOnly = !notice && toolSurface === "none";
  const starters = chatStartersFor(agentAvailability);
  return (
    <div className="empty-state">
      <div className="empty-state__badge">New chat</div>
      <h2>What can I help you with?</h2>
      <p>
        {notice ||
          (textOnly
            ? TEXT_ONLY_AGENT_HINT
            : workspaceHint(projectName, projectId ?? ""))}
      </p>
      {onUseStarter && starters.length > 0 ? (
        <div
          className="empty-state__starters"
          role="group"
          aria-label="Start with an example request"
        >
          {starters.map((starter) => (
            <button
              key={starter.label}
              type="button"
              className="admin-panel__action-btn"
              onClick={() => onUseStarter(starter.prompt)}
            >
              {starter.label}
            </button>
          ))}
        </div>
      ) : null}
      {notice || textOnly ? (
        agentName && agentAvailability !== "unavailable" ? (
          <p className="empty-state__secondary">Agent: {agentName}.</p>
        ) : null
      ) : (
        <p className="empty-state__secondary">
          Need sources first?{" "}
          <a href={knowledgeDocumentsHref(projectId)}>
            Add documents in Knowledge
          </a>
          .{agentName ? ` Agent: ${agentName}.` : ""}
        </p>
      )}
    </div>
  );
}
