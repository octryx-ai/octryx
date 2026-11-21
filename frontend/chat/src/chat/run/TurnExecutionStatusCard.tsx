import { LoadingState } from "../../layout/LoadingState";
import { presentWorkflowChecks } from "./turnWorkflowChecks";
import type {
  TurnExecutionSummaryLoad,
  WorkflowDecisionChoice,
} from "./turnExecutionSummary.types";
import { presentAnswerEvidence } from "./turnAnswerEvidence";
import { turnStateReasonText } from "./turnStateReason";
import { isCompactTurnStatus } from "./turnStatusCompact";
import { WorkflowDecisionOptions } from "./WorkflowDecisionOptions";
import {
  presentNextAction,
  presentTurnExecutionState,
  shouldShowTurnExecutionCard,
} from "./turnExecutionSummaryPresentation";

export function TurnExecutionStatusCard({
  load, onRetry, onOpenDetails, detailsLoading = false, onWorkflowDecision, decisionsDisabled = false,
}: {
  load: TurnExecutionSummaryLoad;
  onRetry: () => void;
  onOpenDetails?: () => void;
  detailsLoading?: boolean;
  onWorkflowDecision?: (choice: WorkflowDecisionChoice) => Promise<void>;
  decisionsDisabled?: boolean;
}) {
  if (!shouldShowTurnExecutionCard(load)) return null;
  if (load.status !== "ready") return notReadyCard(load, onRetry);

  const { summary } = load;
  const state = presentTurnExecutionState(summary.state);
  const nextAction = presentNextAction(summary.nextAction);
  const evidence = presentAnswerEvidence(summary.answerEvidence);
  const checks = presentWorkflowChecks(summary.workflowChecks);
  // Only the exact benign terminal status folds its explanation; everything else stays open.
  const compact = isCompactTurnStatus(summary);

  return (
    <section
      className={`turn-exec-card turn-exec-card--${state.tone}${compact ? " turn-exec-card--compact" : ""}`}
      aria-label="Turn execution status"
      data-state-tone={state.tone}
    >
      {statusRow(summary, state, evidence, checks, onOpenDetails, detailsLoading)}
      {statusExplanation(summary, state, evidence, compact)}
      {nextAction ? (
        <p className="turn-exec-card__next">
          <span className="turn-exec-card__muted">Next: </span>
          {nextAction}
        </p>
      ) : null}
      {summary.decisionRequest && onWorkflowDecision ? (
        <WorkflowDecisionOptions
          request={summary.decisionRequest}
          disabled={decisionsDisabled}
          onChoose={onWorkflowDecision}
        />
      ) : null}
    </section>
  );
}

type ReadyLoad = Extract<TurnExecutionSummaryLoad, { status: "ready" }>;

// The card while the status loads, failed or is not available; nothing for any other state.
function notReadyCard(load: TurnExecutionSummaryLoad, onRetry: () => void) {
  if (load.status === "loading") {
    return (
      <section
        className="turn-exec-card turn-exec-card--pending"
        aria-label="Turn execution status"
        aria-busy="true"
      >
        {/* An outline instead of a lasting "Loading…" text; after 10 s "Try again" loads it again. */}
        <LoadingState label="the status of this answer" variant="page" rows={1} onRetry={onRetry} />
      </section>
    );
  }

  if (load.status === "error") {
    return (
      <section
        className="turn-exec-card turn-exec-card--error"
        aria-label="Turn execution status"
      >
        <span className="turn-exec-card__muted" role="alert">
          Status not available.
        </span>
        <button
          type="button"
          className="turn-exec-card__action"
          onClick={onRetry}
        >
          Try again
        </button>
      </section>
    );
  }

  if (load.status === "unavailable") {
    return (
      <section
        className="turn-exec-card turn-exec-card--neutral"
        aria-label="Turn execution status"
      >
        <span className="turn-exec-card__badge">Unavailable</span>
        <span className="turn-exec-card__muted">
          {load.reason === "unsupported_version"
            ? "This execution status format is not supported by this client."
            : "No execution status is recorded for this turn."}
        </span>
      </section>
    );
  }

  return null;
}

// Why the run is in this state, and what the evidence means; folded under "About this status" when compact.
function statusExplanation(
  summary: ReadyLoad["summary"],
  state: ReturnType<typeof presentTurnExecutionState>,
  evidence: ReturnType<typeof presentAnswerEvidence>,
  compact: boolean,
) {
  const reason = (
    <p className="turn-exec-card__reason">
      {turnStateReasonText(summary.state, summary.stateReason.code, summary.stateReason.text, state.description)}
    </p>
  );
  const evidenceExplanation = evidence?.explain ? (
    <p className="turn-exec-card__reason" data-evidence-explanation="">
      {evidence.description}
    </p>
  ) : null;
  return compact ? (
    <details className="turn-exec-card__explain">
      <summary>About this status</summary>
      {reason}
      {evidenceExplanation}
    </details>
  ) : (
    <>
      {reason}
      {evidenceExplanation}
    </>
  );
}

// Badge, evidence, checks, reply format and the details button in one row.
function statusRow(
  summary: ReadyLoad["summary"],
  state: ReturnType<typeof presentTurnExecutionState>,
  evidence: ReturnType<typeof presentAnswerEvidence>,
  checks: ReturnType<typeof presentWorkflowChecks>,
  onOpenDetails: (() => void) | undefined,
  detailsLoading: boolean,
) {
  return (
    <div className="turn-exec-card__row">
      <span className="turn-exec-card__badge">{state.label}</span>
      {evidence ? (
        <span className="turn-exec-card__meta" title={evidence.description}>
          Evidence:{" "}
          <strong data-evidence-tone={evidence.tone}>{evidence.label}</strong>
        </span>
      ) : null}
      {checks ? (
        <span className="turn-exec-card__meta" title={checks.description} data-workflow-checks="">
          Checks: <strong data-evidence-tone={checks.tone}>{checks.label}</strong>
        </span>
      ) : null}
      {summary.replyContract?.status === "satisfied" ? (
        <span
          className="turn-exec-card__meta"
          data-reply-format="checked"
          title="The agent's reply matched its declared output format."
        >
          Reply format: <strong>checked</strong>
        </span>
      ) : null}
      {onOpenDetails ? (
        <button
          type="button"
          className="turn-exec-card__action"
          onClick={onOpenDetails}
          disabled={detailsLoading}
          aria-label="Open execution details"
        >
          {detailsLoading ? "Opening…" : "Details"}
        </button>
      ) : null}
    </div>
  );
}
