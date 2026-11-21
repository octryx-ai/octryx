import { workflowClass, workflowClassLabel, workflowOptionTitle, workflowStepsText } from "./workflowClass";
import { WorkflowIcon } from "../ChatShellIcons";
import { AUTOMATIC_LABEL } from "./automaticWorkflow";
import type { ComposerShellProps } from "../composerShellTypes";

type ModeOfWorkPillProps = Pick<
  ComposerShellProps,
  | "composerDisabled"
  | "workflowOptions"
  | "selectedWorkflowKey"
  | "setSelectedWorkflowKey"
  | "workflowPillLabel"
  | "selectedWorkflowCapability"
>;

// The display names the explicit choice, or — for Automatic — what the
// platform or model chose and why (workflowPillLabel carries that reason).
function pillText({ workflowOptions, selectedWorkflowKey, workflowPillLabel }: ModeOfWorkPillProps) {
  const selectedOption = workflowOptions.find((option) => option.key === selectedWorkflowKey);
  const explicitTitle = selectedWorkflowKey
    ? (selectedOption ? workflowOptionTitle(selectedOption, workflowOptions) : selectedWorkflowKey)
    : null;
  const displayLabel = explicitTitle ?? (workflowPillLabel || AUTOMATIC_LABEL);
  // The selected workflow's class badge and its steps (strict | guided) in the tooltip.
  const selectedClass = selectedWorkflowKey ? workflowClass(selectedOption) : "";
  const stepsText = workflowStepsText(selectedOption);
  const tooltip = [`Workflow for the next message: ${displayLabel}`, stepsText].filter(Boolean).join("\n");
  return { displayLabel, selectedOption, selectedClass, stepsText, tooltip };
}

function ModeBadge({ selectedClass, capability }: {
  selectedClass: string;
  capability: ModeOfWorkPillProps["selectedWorkflowCapability"];
}) {
  return selectedClass ? (
    <span className={`composer-pill__badge composer-pill__badge--${selectedClass}`} data-workflow-class={selectedClass}>
      {workflowClassLabel(selectedClass)}
    </span>
  ) : capability ? (
    <span
      className={`composer-pill__badge composer-pill__badge--${capability}`}
    >
      {capability === "diagnosis"
        ? "Diagnosis"
        : "Change"}
    </span>
  ) : null;
}

function WorkflowChoices({ workflowOptions, selectedWorkflowKey }: Pick<ModeOfWorkPillProps, "workflowOptions" | "selectedWorkflowKey">) {
  return (
    <optgroup label="Workflows">
      <option value="">{AUTOMATIC_LABEL}</option>
      {selectedWorkflowKey &&
      !workflowOptions.some(
        (option) => option.key === selectedWorkflowKey,
      ) ? (
        <option value={selectedWorkflowKey} disabled>
          {selectedWorkflowKey} · unavailable in this Workspace
        </option>
      ) : null}
      {workflowOptions.map((option) => (
        <option key={option.key} value={option.key}>
          {workflowOptionTitle(option, workflowOptions)}
          {option.selection === "no_workflow"
            ? ""
            : ` · ${workflowClassLabel(workflowClass(option)) || "Change"}`}
        </option>
      ))}
    </optgroup>
  );
}

// One workflow control: a single pill shows what
// applies to the next turn — "Automatic", what the platform or the model chose
// with its reason, or the explicit choice — and is itself the select. There is
// no second chip or "Advanced" disclosure, so the state is never shown twice.
export function ModeOfWorkPill(props: ModeOfWorkPillProps) {
  const {
    composerDisabled,
    workflowOptions,
    selectedWorkflowKey,
    setSelectedWorkflowKey,
    selectedWorkflowCapability,
  } = props;
  const { displayLabel, selectedOption, selectedClass, stepsText, tooltip } = pillText(props);

  return (
    <label
      className={`composer-pill composer-pill--workflow${selectedWorkflowKey ? " composer-pill--explicit" : ""}`}
      title={tooltip}
      data-testid="composer-workflow-chip"
    >
      <span className="composer-pill__display">
        <WorkflowIcon />
        {/* A caption names the choice, so "Automatic" here never reads like the model pill's. */}
        <span className="composer-pill__caption">Workflow</span>
        <span className="composer-pill__text">{displayLabel}</span>
        <ModeBadge selectedClass={selectedClass} capability={selectedWorkflowCapability} />
        {stepsText ? (
          <span className="composer-pill__revision" data-workflow-steps="">
            {`· ${selectedOption?.steps?.length ?? 0} steps`}
          </span>
        ) : null}
      </span>
      <select
        aria-label="Workflow"
        value={selectedWorkflowKey}
        disabled={composerDisabled}
        onChange={(event) => setSelectedWorkflowKey(event.target.value)}
      >
        <WorkflowChoices workflowOptions={workflowOptions} selectedWorkflowKey={selectedWorkflowKey} />
      </select>
    </label>
  );
}
