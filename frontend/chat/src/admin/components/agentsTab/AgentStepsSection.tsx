import { AgentStepFormPanel } from "./AgentStepFormPanel";
import { stepToolsLabel } from "./agentWorkspaceModel";
import { toolUseState } from "./stepToolSelection";

type AgentStepsSectionProps = {
  agentId: string;
  steps: any[];
  ctx: Record<string, unknown>;
};

// The one step editor of an agent: order, instructions, success
// criteria and tool restriction of every step, edited through the governed
// panel step API (each change appends a draft revision).
// Matches the runtime rule (`agent/core/guards/step_tool_requirement.py`).
function toolUseLabel(step: any): string {
  const state = toolUseState(JSON.stringify(step.stepConfig || {}), (step.allowedTools || []).join(","));
  const text = state.value === "required" ? "Must use one of its tools before the step completes" : "May answer without tools";
  return state.source === "default" ? `${text} (default)` : text;
}

export function AgentStepsSection({ agentId, steps, ctx }: AgentStepsSectionProps) {
  const { agentStepFormFor, handleDeleteAgentStep, handleMoveAgentStep, handleOpenAgentStepForm } =
    ctx as Record<string, any>;
  const ordered = [...steps].sort((a, b) => a.position - b.position);
  const formOpen = agentStepFormFor === agentId;

  return (
    <section className="agent-workspace__section" aria-labelledby="agent-workspace-steps">
      <div className="agent-workspace__section-head">
        <h3 id="agent-workspace-steps">Steps ({ordered.length})</h3>
        <button type="button" className="admin-panel__action-btn" onClick={() => handleOpenAgentStepForm(agentId, null)}>
          + Add step
        </button>
      </div>
      <p className="agent-workspace__hint">
        Steps run in this order. Without steps the agent works from its goal and prompts alone.
      </p>
      {/* Add and edit open the same side panel over the page; the list stays as it is underneath. */}
      {formOpen ? <AgentStepFormPanel agentId={agentId} ctx={ctx} /> : null}
      <ol className="agent-workspace__steps">
        {ordered.map((step, index) => (
          <li key={step.id} className="agent-workspace__step">
            <div className="agent-workspace__step-head">
              <span className="agent-workspace__step-pos">{index + 1}</span>
              <strong>{step.name}</strong>
              <span className="admin-panel__badge">{step.stepType}</span>
              {step.isEnabled === false ? <span className="admin-panel__badge admin-panel__badge--inactive">Disabled</span> : null}
            </div>
            {step.instructions ? <p className="agent-workspace__step-text">{step.instructions}</p> : null}
            <dl className="agent-workspace__step-facts">
              <dt>Done when</dt>
              <dd>{step.successCriteria || "No success criteria"}</dd>
              <dt>Tools</dt>
              <dd>{stepToolsLabel(step.allowedTools)}</dd>
              <dt>Tool use</dt>
              <dd>{toolUseLabel(step)}</dd>
            </dl>
            {step.stepConfig && Object.keys(step.stepConfig).length > 0 ? (
              <details className="agent-workspace__details">
                <summary>Step configuration</summary>
                <pre>{JSON.stringify(step.stepConfig, null, 2)}</pre>
              </details>
            ) : null}
            <div className="agent-workspace__step-actions">
              <button type="button" className="admin-panel__icon-btn" aria-label={`Move ${step.name} up`}
                disabled={index === 0} onClick={() => void handleMoveAgentStep(agentId, step.id, "up")}>↑</button>
              <button type="button" className="admin-panel__icon-btn" aria-label={`Move ${step.name} down`}
                disabled={index === ordered.length - 1} onClick={() => void handleMoveAgentStep(agentId, step.id, "down")}>↓</button>
              <button type="button" className="admin-panel__action-btn" onClick={() => handleOpenAgentStepForm(agentId, step)}>
                Edit
              </button>
              <button type="button" className="admin-panel__danger-btn" onClick={() => void handleDeleteAgentStep(agentId, step)}>
                Delete
              </button>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
