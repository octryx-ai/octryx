import { useState } from "react";
import type { TurnDecisionRequest, WorkflowDecisionChoice } from "./turnExecutionSummary.types";

// Renders a workflow clarification's closed decision options as buttons.
// The options come from the structured `decision_request` of the turn
// execution summary, never from the assistant's message text. Choosing one
// sends it as `workflow_decisions` with the next message.
export function WorkflowDecisionOptions({
  request,
  disabled,
  onChoose,
}: {
  request: TurnDecisionRequest;
  disabled: boolean;
  onChoose: (choice: WorkflowDecisionChoice) => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState<string | null>(null);

  async function choose(value: string, label: string) {
    if (disabled || submitting) {
      return;
    }
    setSubmitting(value);
    try {
      await onChoose({ decisionKey: request.decisionKey, value, label });
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <div
      className="turn-exec-card__decisions"
      role="group"
      aria-label="Workflow decision"
    >
      {request.options.map((option) => {
        const recorded = option.value === request.recordedValue;
        return (
          <button
            key={option.value}
            type="button"
            className="turn-exec-card__decision"
            data-decision-value={option.value}
            disabled={disabled || recorded || submitting !== null}
            aria-pressed={recorded}
            onClick={() => void choose(option.value, option.label)}
          >
            {submitting === option.value ? "Sending…" : option.label}
            {recorded ? (
              <span className="turn-exec-card__decision-note"> (current)</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
