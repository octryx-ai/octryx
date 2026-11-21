import type { ReactNode } from "react";

import type { StartBudgetBody } from "./startCardChoices";
import { runStartDecision, useWorkflowStartCard } from "./useWorkflowStartCard";
import {
  WorkflowStartActions,
  WorkflowStartChoices,
  WorkflowStartItem,
  WorkflowStartLists,
  WorkflowStartOutcomeLines,
} from "./WorkflowStartParts";
import { needsConfiguration, startBlockedReason, type WorkflowStartView } from "./workflowStartModel";
import "./workflowStartCard.css";

type WorkflowStartCardProps = {
  view: WorkflowStartView;
  reason: string | null;
  decided: "apply" | "skip" | null;
  disabled: boolean;
  // Throws a refusal in words (409 missing repository, 422 not offered); the card shows it.
  onStart: (runOn: string, repository: string, model: string, budget: StartBudgetBody | null) => Promise<void>;
  onSkip: () => Promise<void>;
  otherOpen: boolean;
  onOther: (() => void) | null;
  picker: ReactNode;
};

// The start card of a phased workflow (contract `phased_start.py`): the held turn waits for one confirmation that
// creates or uses the Work item and starts the run in a chat of its own. "Start" sends `apply` with the chosen
// "Run on", its model, repository and cost budget (the server puts it on the Work item, new or
// existing, before the run); "Don't start" sends `skip`; "Other workflow…" is the caller's picker. Without a
// repository a run that needs one cannot start, so Start waits for the choice. After the start the card links to the
// run; a refused start shows what was already made (the Jira issue, the Work item), says why, and offers Start again.
export function WorkflowStartCard({
  view,
  reason,
  decided,
  disabled,
  onStart,
  onSkip,
  otherOpen,
  onOther,
  picker,
}: WorkflowStartCardProps) {
  const state = useWorkflowStartCard(view);
  const { busy, problem } = state;

  const { outcome } = view;
  const started = outcome.kind === "started" ? outcome : null;
  const failed = outcome.kind === "error" ? outcome : null;
  const skipped = decided === "skip";
  // After an answer the card is a record, except after a refused start: then it can be answered again.
  // A refusal that needs configuration first (no Workspace) is not answered again here: it says what to configure.
  const actionable = !started && !skipped && !needsConfiguration(outcome) && (decided !== "apply" || Boolean(failed));
  const tone = started ? "success" : failed ? "error" : skipped ? "neutral" : "attention";
  const progress = started ?? failed;
  const blocked = startBlockedReason(view, state.repository);
  const locked = disabled || busy !== null;

  return (
    <section
      className={`workflow-start workflow-start--${tone}`}
      aria-label="Start a workflow"
      data-testid="workflow-start-card"
    >
      <header className="workflow-start__head">
        <span className="workflow-start__eyebrow">{started ? "Workflow started" : "Start a workflow"}</span>
        <h3 className="workflow-start__title">{view.summary}</h3>
        {reason && !started ? <p className="workflow-start__quiet">{reason}</p> : null}
      </header>

      <WorkflowStartItem view={view} progress={progress} />
      <WorkflowStartLists view={view} progress={progress} />
      <WorkflowStartChoices view={view} state={state} actionable={actionable} locked={locked} failed={failed} />
      <WorkflowStartOutcomeLines view={view} started={started} failed={failed} problem={problem} skipped={skipped} decided={decided} />

      {actionable ? (
        <WorkflowStartActions
          outcome={outcome}
          busy={busy}
          locked={locked}
          blocked={blocked}
          otherOpen={otherOpen}
          onOther={onOther}
          onRun={(kind) => void runStartDecision(kind, state, { disabled, blocked, onStart, onSkip })}
        />
      ) : null}
      {otherOpen && actionable ? picker : null}
    </section>
  );
}
