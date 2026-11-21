import { agentPageHref } from "../../agentLinks";
import type { PanelTaskRow, PanelTaskStepRow } from "../taskTypes";

// Steps of an Action explicitly bound to its agent. Such an Action runs its selected agent
// directly; the agent's own instructions and steps are what run, and they are edited only on the
// agent's page. The server refuses enabled Action steps on a bound Action, so this offers
// no step editor. Saved Action steps are listed read-only, as stored, without claiming they ran.
export function BoundActionAgentSteps({
  task,
  steps,
}: {
  task: PanelTaskRow;
  steps: PanelTaskStepRow[];
}) {
  const agentId = task.config?.agent_definition_id;
  const hasAgent = typeof agentId === "string" && agentId.trim() !== "";
  const sortedSteps = [...steps].sort((a, b) => a.position - b.position);

  return (
    <div data-testid="bound-action-agent-steps">
      <div className="task-item__runs-header">
        <span
          style={{
            fontWeight: 600,
            fontSize: "var(--ds-text-sm)",
            color: "var(--muted-strong)",
          }}
        >
          Steps
        </span>
      </div>
      <div className="admin-form-help" style={{ padding: "0 0.5rem 0.5rem" }}>
        This action runs its selected agent directly. Its instructions and steps
        belong to that agent and are edited on the agent&apos;s page.{" "}
        {hasAgent ? (
          <a
            href={agentPageHref(agentId)}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open agent ↗
          </a>
        ) : (
          <span className="admin-panel__cell--muted">
            This server does not report the selected agent.
          </span>
        )}
      </div>
      {sortedSteps.length ? (
        <div className="steps-list" data-testid="bound-action-saved-steps">
          <div
            className="admin-panel__cell--muted"
            style={{ padding: "0 0.5rem", fontSize: "var(--ds-text-xs)" }}
          >
            Saved action steps, shown as stored. They are not edited here. A
            direct agent run does not execute them, and while any of them is
            enabled, runs of this action are refused.
          </div>
          {sortedSteps.map((step) => (
            <div
              key={step.id}
              className={`step-item ${!step.is_enabled ? "step-item--disabled" : ""}`}
            >
              <div className="step-item__pos">{step.position}</div>
              <div className="step-item__type">{step.step_type}</div>
              <div className="step-item__info">
                <div className="step-item__name">{step.name}</div>
                <div className="step-item__meta">
                  {step.is_enabled ? "enabled" : "disabled"}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
