import { useState, type ReactNode } from "react";

import { BrainIcon } from "../ChatShellIcons";
import { ModeOfWorkPill } from "./ModeOfWorkPill";
import { shortRuntimeLabel } from "../chatOnboarding";
import type { ComposerShellProps } from "../composerShellTypes";
import { THINKING_SWITCH, THINKING_SWITCH_TITLES } from "./thinkingSwitch";

export type ComposerRoutingPillsProps = Pick<
  ComposerShellProps,
  | "composerDisabled"
  | "runtimePillLabel"
  | "selectedRuntimeTargetId"
  | "setSelectedRuntimeTargetId"
  | "runtimeOptions"
  | "selectedThinkingLevel"
  | "setSelectedThinkingLevel"
  | "workflowOptions"
  | "selectedWorkflowKey"
  | "setSelectedWorkflowKey"
  | "workflowPillLabel"
  | "selectedWorkflowCapability"
> & {
  // The "Run on" control; with a device target the Server-only pills hide.
  runOn?: ReactNode;
  hideServerOnly?: boolean;
};

// Workflow / model / thinking selection. Extracted from `ComposerFooterControls` so the same markup can be rendered
// inline on desktop and inside the compact composer disclosure on phones.
// One control per choice. The Workspace is the active one of the global switch
// (no composer select); the model is one pill reading "Automatic · <model>" from the server's runtime options; thinking
// is one switch (Off / Quick / Thorough). Only where the request runs ("Run on") waits under "Advanced"; with a device
// chosen it stays visible, so the run location is never hidden.
export function ComposerRoutingPills({
  runOn,
  hideServerOnly = false,
  composerDisabled,
  runtimePillLabel,
  selectedRuntimeTargetId,
  setSelectedRuntimeTargetId,
  runtimeOptions,
  selectedThinkingLevel,
  setSelectedThinkingLevel,
  workflowOptions,
  selectedWorkflowKey,
  setSelectedWorkflowKey,
  workflowPillLabel,
  selectedWorkflowCapability,
}: ComposerRoutingPillsProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const modelLabel = shortRuntimeLabel(runtimePillLabel);
  return (
    <div
      className="composer__command-controls"
      aria-label="Composer routing controls"
    >
      {hideServerOnly ? null : (
        <ModeOfWorkPill
          composerDisabled={composerDisabled}
          workflowOptions={workflowOptions}
          selectedWorkflowKey={selectedWorkflowKey}
          setSelectedWorkflowKey={setSelectedWorkflowKey}
          workflowPillLabel={workflowPillLabel}
          selectedWorkflowCapability={selectedWorkflowCapability}
        />
      )}
      {hideServerOnly ? null : (
        <label className="composer-pill composer-pill--runtime" title={`Model: ${runtimePillLabel}`}
          data-testid="composer-model-pill">
          <span className="composer-pill__display">
            <BrainIcon />
            <span className="composer-pill__caption">Model</span>
            <span className="composer-pill__text">{modelLabel}</span>
          </span>
          <select
            aria-label="Model"
            value={selectedRuntimeTargetId}
            disabled={composerDisabled}
            onChange={(event) => setSelectedRuntimeTargetId(event.target.value)}
          >
            {runtimeOptions.map((option) => (
              <option
                key={option.value || "automatic"}
                value={option.value}
                disabled={Boolean(option.disabled || option.disabledReason)}
              >
                {option.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="composer-switch" role="group" aria-label="Thinking">
        {THINKING_SWITCH.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`composer-switch__option${selectedThinkingLevel === option.value ? " is-active" : ""}`}
            aria-pressed={selectedThinkingLevel === option.value}
            title={THINKING_SWITCH_TITLES[option.value]}
            disabled={composerDisabled}
            onClick={() => setSelectedThinkingLevel(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {runOn && !hideServerOnly ? (
        <button
          type="button"
          className={`composer-action-button composer-action-button--ghost composer-switch__advanced${advancedOpen ? " composer-action-button--active" : ""}`}
          aria-expanded={advancedOpen}
          title="Where this request runs"
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          <span>{advancedOpen ? "Fewer options" : "Advanced"}</span>
        </button>
      ) : null}
      {advancedOpen || hideServerOnly ? runOn : null}
    </div>
  );
}
