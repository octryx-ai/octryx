import type { ToolEvent } from "../chatThreadTypes";
import { planStepMarker, turnPlanFromToolEvents } from "./turnPlan";

// The agent's plan inline in the transcript (read-only), in the same
// collapsible style as the execution diff. Hidden when the turn kept no plan.
export function TurnPlanSummary({
  events,
}: {
  events: ToolEvent[] | null | undefined;
}) {
  const plan = turnPlanFromToolEvents(events);
  if (!plan) {
    return null;
  }
  return (
    <details className="turn-diff-summary turn-plan-summary" aria-label="Plan">
      <summary className="turn-diff-summary__header">
        <div className="turn-diff-summary__header-main">
          <div className="turn-diff-summary__headline">
            <span className="turn-diff-summary__eyebrow">Plan</span>
            <span className="turn-diff-summary__title">
              {plan.completed}/{plan.total} done
            </span>
            {plan.current ? (
              <span className="turn-diff-summary__preview">
                Now: {plan.current}
              </span>
            ) : null}
          </div>
        </div>
        <span className="turn-diff-summary__toggle">
          <span className="turn-diff-summary__toggle-copy">Open</span>
          <span className="turn-diff-summary__caret" aria-hidden="true">
            {">"}
          </span>
        </span>
      </summary>
      <div className="turn-diff-summary__body">
        <section className="turn-diff-summary__section">
          {plan.steps.map((step) => (
            <div
              key={step.id}
              className="turn-diff-summary__row"
              data-plan-status={step.status}
            >
              <div className="turn-diff-summary__row-main">
                <span aria-hidden="true">{planStepMarker(step.status)}</span>{" "}
                {step.status === "completed" ? (
                  <s>{step.subject}</s>
                ) : (
                  step.subject
                )}
              </div>
            </div>
          ))}
          {plan.truncated ? (
            <div className="turn-diff-summary__row-subtle">
              {plan.total - plan.steps.length} more steps
            </div>
          ) : null}
        </section>
      </div>
    </details>
  );
}
