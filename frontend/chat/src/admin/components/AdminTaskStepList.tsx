import type { PanelAgentRow, PanelTaskStepRow } from "./taskTypes";

type StepActions = {
  taskId: string;
  panelAgents: PanelAgentRow[];
  onMoveStep: (
    taskId: string,
    stepId: string,
    direction: "up" | "down",
  ) => Promise<void>;
  onOpenStepForm: (taskId: string, step?: PanelTaskStepRow) => void;
  onDeleteStep: (taskId: string, stepId: string) => Promise<void>;
};

const STEP_TYPE_COLORS: Record<string, string> = {
  connector_fetch: "#60a5fa",
  analysis: "#a78bfa",
  sub_agent_spawn: "#f59e0b",
  verification: "#34d399",
  condition: "#f97316",
  output: "#94a3b8",
};

export function AdminTaskStepList({
  taskId,
  steps,
  panelAgents,
  onMoveStep,
  onOpenStepForm,
  onDeleteStep,
}: StepActions & { steps: PanelTaskStepRow[] }) {
  if (steps.length === 0) {
    return (
      <div
        className="admin-panel__cell--muted"
        style={{ padding: "0.5rem", fontSize: "var(--ds-text-sm)" }}
      >
        No steps yet. Add one above.
      </div>
    );
  }

  const sortedSteps = [...steps].sort((a, b) => a.position - b.position);

  return (
    <>
      {sortedSteps.map((step, index) => (
        <StepItem
          key={step.id}
          taskId={taskId}
          step={step}
          isFirst={index === 0}
          isLast={index === sortedSteps.length - 1}
          panelAgents={panelAgents}
          onMoveStep={onMoveStep}
          onOpenStepForm={onOpenStepForm}
          onDeleteStep={onDeleteStep}
        />
      ))}
    </>
  );
}

function StepItem({
  taskId,
  step,
  isFirst,
  isLast,
  panelAgents,
  onMoveStep,
  onOpenStepForm,
  onDeleteStep,
}: StepActions & { step: PanelTaskStepRow; isFirst: boolean; isLast: boolean }) {
  const runtimeLabel =
    step.runtime_selector?.runtime_target_id || "default";

  return (
    <div
      className={`step-item ${!step.is_enabled ? "step-item--disabled" : ""}`}
    >
      <div className="step-item__pos">{step.position}</div>

      <div
        className="step-item__type"
        style={{ color: STEP_TYPE_COLORS[step.step_type] || "#94a3b8" }}
      >
        {step.step_type}
      </div>

      <StepInfo step={step} panelAgents={panelAgents} />

      <div className="step-item__runtime">
        <span className="task-item__badge">{runtimeLabel}</span>
        {step.step_type === "verification" ? (
          <span className="task-item__badge task-item__badge--secondary">
            max fix: {step.max_fix_attempts}
          </span>
        ) : null}
      </div>

      <StepItemActions
        taskId={taskId}
        step={step}
        isFirst={isFirst}
        isLast={isLast}
        onMoveStep={onMoveStep}
        onOpenStepForm={onOpenStepForm}
        onDeleteStep={onDeleteStep}
      />
    </div>
  );
}

function StepInfo({ step, panelAgents }: { step: PanelTaskStepRow; panelAgents: PanelAgentRow[] }) {
  const agentDefinitionId = (
    step.connector_params as { agent_definition_id?: unknown }
  ).agent_definition_id;

  return (
    <div className="step-item__info">
      <div className="step-item__name">{step.name}</div>

      {step.connector ? (
        <div className="step-item__meta">
          connector: {step.connector}
          {step.connector_action ? ` / ${step.connector_action}` : ""}
        </div>
      ) : null}

      {agentDefinitionId !== undefined ? (
        <div
          className="step-item__meta"
          style={{
            color: agentDefinitionId === "" ? "#9ca3af" : "#6366f1",
          }}
        >
          agent:{" "}
          {agentDefinitionId === ""
            ? "suppressed"
            : panelAgents.find(
                (agent) => agent.id === String(agentDefinitionId),
              )?.name || String(agentDefinitionId).slice(0, 8)}
        </div>
      ) : null}

      {step.context_fields?.length ? (
        <div className="step-item__meta" style={{ color: "#0891b2" }}>
          ctx: {step.context_fields.join(", ")}
        </div>
      ) : null}

      {step.instructions ? (
        <div className="step-item__instructions">
          {step.instructions.slice(0, 80)}
          {step.instructions.length > 80 ? "…" : ""}
        </div>
      ) : null}
    </div>
  );
}

function StepItemActions({
  taskId,
  step,
  isFirst,
  isLast,
  onMoveStep,
  onOpenStepForm,
  onDeleteStep,
}: Omit<StepActions, "panelAgents"> & { step: PanelTaskStepRow; isFirst: boolean; isLast: boolean }) {
  return (
    <div className="step-item__actions">
      <button
        type="button"
        className="admin-panel__icon-btn"
        title="Move up"
        disabled={isFirst}
        onClick={() => void onMoveStep(taskId, step.id, "up")}
      >
        ↑
      </button>
      <button
        type="button"
        className="admin-panel__icon-btn"
        title="Move down"
        disabled={isLast}
        onClick={() => void onMoveStep(taskId, step.id, "down")}
      >
        ↓
      </button>
      <button
        type="button"
        className="admin-panel__icon-btn"
        title="Edit"
        onClick={() => onOpenStepForm(taskId, step)}
      >
        ✏
      </button>
      <button
        type="button"
        className="admin-panel__danger-btn"
        style={{ fontSize: "var(--ds-text-xs)" }}
        onClick={() => void onDeleteStep(taskId, step.id)}
      >
        Del
      </button>
    </div>
  );
}
