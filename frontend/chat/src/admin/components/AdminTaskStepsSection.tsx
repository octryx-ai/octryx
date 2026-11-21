import { BoundActionAgentSteps } from "./automation/BoundActionAgentSteps";
import { bindingState } from "./automation/actionDispatchBinding";
import {
  StepsEditor,
  TaskDependencySection,
  type AdminTaskStepsSectionProps,
} from "./AdminTaskStepsSectionParts";

export function AdminTaskStepsSection(props: AdminTaskStepsSectionProps) {
  const { isExpanded, task, taskSteps } = props;
  if (!isExpanded) {
    return null;
  }

  const steps = taskSteps[task.id] || [];
  // Only an explicit agent binding replaces the step editor (and with it any open step form);
  // null, missing or unknown keep it.
  const bound = bindingState(task) === "agent_definition";

  return (
    <div className="task-item__steps">
      <div className="task-item__runs-header">
        <span
          style={{
            fontWeight: 600,
            fontSize: "var(--ds-text-sm)",
            color: "var(--muted-strong)",
          }}
        >
          Action dependencies
        </span>
      </div>

      <TaskDependencySection props={props} />

      {bound ? (
        <BoundActionAgentSteps task={task} steps={steps} />
      ) : (
        <StepsEditor props={props} steps={steps} />
      )}
    </div>
  );
}
