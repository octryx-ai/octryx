// The workflow proposal card above an answer: the pending prompt or the phased start card.
import type { StartBudgetBody } from "./startCardChoices";
import { useState, type Dispatch, type ReactNode, type SetStateAction } from "react";

import type { WorkflowOption } from "../../chatOptionTypes";
import type { WorkflowProposalView } from "../../chatDecisionTypes";
import {
  OTHER_WORKFLOW_LABEL,
  PROPOSAL_ANSWERS,
  proposalReasonText,
  type ProposalAnswer,
} from "../composer/automaticWorkflow";
import { OtherWorkflowPicker } from "./OtherWorkflowPicker";
import { WorkflowStartCard } from "./WorkflowStartCard";
import { workflowStartView } from "./workflowStartModel";
import type { TurnWorkflowProposal, WorkflowDecisionChoice } from "./turnExecutionSummary.types";
import { WorkflowOffer } from "./WorkflowOffer";
type WorkflowProposalOptionsProps = {
  proposal: TurnWorkflowProposal;
  details: WorkflowProposalView | null | undefined;
  disabled: boolean;
  onChoose?: (choice: WorkflowDecisionChoice) => Promise<void>;
  repeatsTurn?: boolean;
  // The turn's own message, sent again when the user accepts an offer.
  offerPrompt?: string | null;
  // The composer's workflow catalog, for "Other workflow…".
  workflowOptions?: readonly WorkflowOption[];
};

// The proposal as the session now sees it: its decision, reason, workflow and title, preferring the session's
// view for the same proposal id.
function currentProposalView(
  proposal: TurnWorkflowProposal,
  details: WorkflowProposalView | null | undefined,
  turnWorkflowKey: string,
) {
  const proposalId = proposal.proposalId;
  const sameProposal = Boolean(proposalId) && details?.proposalId === proposalId;
  const decided = sameProposal ? details?.decision : null;
  // The reason codes of a phased start and of "Other workflow…" read in words; else the server's sentence.
  const reason =
    proposalReasonText(sameProposal ? details?.reasonCode : proposal.reasonCode) ??
    (sameProposal ? details?.reason : null);
  // "Other workflow…" changes the workflow after the turn: the session's view is newer than the turn snapshot.
  const workflowKey = (sameProposal && details?.workflowKey) || turnWorkflowKey;
  const title = (sameProposal && details?.workflowTitle) || proposal.workflowTitle || workflowKey;
  return { proposalId, sameProposal, decided, reason, workflowKey, title };
}

type ProposalActionContext = {
  disabled: boolean;
  submitting: string | null;
  onChoose?: (choice: WorkflowDecisionChoice) => Promise<void>;
  proposalId: string | null | undefined;
  setSubmitting: Dispatch<SetStateAction<string | null>>;
  setOtherOpen: Dispatch<SetStateAction<boolean>>;
};

function proposalActions({ disabled, submitting, onChoose, proposalId, setSubmitting, setOtherOpen }: ProposalActionContext) {
  async function choose(value: ProposalAnswer["value"], label: string, runOn?: string) {
    if (disabled || submitting || !onChoose || !proposalId) {
      return;
    }
    setSubmitting(value);
    try {
      await onChoose({ decisionKey: "workflow_proposal", value, label, proposalId, ...(runOn ? { runOn } : {}) });
    } finally {
      setSubmitting(null);
    }
  }

  // A phased start: its refusal (a missing repository, a run that did not start) is shown on the card itself.
  async function startPhased(runOn: string, repository: string, model: string, budget: StartBudgetBody | null, workflowTitle: string) {
    if (disabled || !onChoose || !proposalId) return;
    await onChoose({
      decisionKey: "workflow_proposal",
      value: "apply",
      label: `Start: ${workflowTitle}`,
      proposalId,
      inline: true,
      ...(runOn ? { runOn } : {}),
      ...(repository ? { repository } : {}),
      ...(model ? { model } : {}),
      ...(budget ? { budget } : {}),
    });
  }

  // Throws the refusal in words; the picker shows it.
  async function chooseOther(key: string, otherTitle: string) {
    if (!onChoose || !proposalId) return;
    await onChoose({
      decisionKey: "workflow_proposal",
      value: "other",
      label: `Other workflow: ${otherTitle}`,
      proposalId,
      workflowKey: key,
    });
    setOtherOpen(false);
  }

  return { choose, startPhased, chooseOther };
}

// Compact proposal card above the answer: the platform proposed a
// published workflow for this turn. A pending proposal is an inline prompt
// like Claude Code's permission prompt: "Allow once" (the message is re-sent
// once with the workflow), "Deny" (re-sent without a workflow) and "Other
// workflow…" (swaps the pending workflow; the card then shows the new one). A
// phased workflow shows its start card instead (`WorkflowStartCard`). Each
// answer decides the proposal's one governed approval record. An offered
// workflow shows once per user turn: `repeatsTurn` marks a later message of the
// same turn. A pending proposal is never suppressed. The closed fields come
// from the turn execution summary; the short reason comes from the thread's
// own session state, and only for the same proposal id.
export function WorkflowProposalOptions({
  proposal,
  details,
  disabled,
  onChoose,
  repeatsTurn = false,
  offerPrompt = null,
  workflowOptions = [],
}: WorkflowProposalOptionsProps) {
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [otherOpen, setOtherOpen] = useState(false);
  if (proposal.status === "offered" && proposal.workflowKey) {
    if (repeatsTurn) return null;
    return (
      <WorkflowOffer
        proposal={proposal}
        details={details}
        disabled={disabled}
        onChoose={onChoose}
        offerPrompt={offerPrompt}
      />
    );
  }
  if (proposal.status !== "needs_confirmation" || !proposal.workflowKey) {
    return null;
  }
  const { proposalId, sameProposal, decided, reason, workflowKey, title } = currentProposalView(proposal, details, proposal.workflowKey);
  return renderPendingProposal({
    details, disabled, onChoose, workflowOptions, submitting, setSubmitting, otherOpen, setOtherOpen,
    view: { proposalId, sameProposal, decided, reason, workflowKey, title },
  });
}

type PendingProposalContext = Required<Pick<WorkflowProposalOptionsProps, "workflowOptions">>
  & Pick<WorkflowProposalOptionsProps, "details" | "disabled" | "onChoose">
  & Pick<ProposalActionContext, "submitting" | "setSubmitting" | "setOtherOpen"> & {
    otherOpen: boolean;
    view: ReturnType<typeof currentProposalView>;
  };

// A pending proposal: the phased start card, or the prompt with its answers and "Other workflow…".
function renderPendingProposal(context: PendingProposalContext) {
  const { details, disabled, onChoose, workflowOptions, submitting, setSubmitting, otherOpen, setOtherOpen } = context;
  const { proposalId, sameProposal, decided, reason, workflowKey, title } = context.view;
  const answerable = Boolean(onChoose && proposalId);
  const { choose, startPhased, chooseOther } = proposalActions({
    disabled, submitting, onChoose, proposalId, setSubmitting, setOtherOpen,
  });

  const picker = answerable ? (
    <OtherWorkflowPicker
      options={workflowOptions}
      currentKey={workflowKey}
      disabled={disabled}
      onPick={chooseOther}
      onClose={() => setOtherOpen(false)}
    />
  ) : null;
  const toggleOther = answerable ? () => setOtherOpen((open) => !open) : null;

  const start = sameProposal ? workflowStartView(details) : null;
  if (start) {
    return (
      <WorkflowStartCard
        view={start}
        reason={reason ?? null}
        decided={decided ?? null}
        disabled={disabled || !answerable}
        onStart={(runOn, repository, model, budget) => startPhased(runOn, repository, model, budget, start.workflowTitle)}
        onSkip={() => choose("skip", `Don't start: ${start.workflowTitle}`)}
        otherOpen={otherOpen}
        onOther={toggleOther}
        picker={picker}
      />
    );
  }
  return (
    <PendingProposalCard title={title} reason={reason} answerable={answerable} decided={decided} answers={PROPOSAL_ANSWERS}
      disabled={disabled} submitting={submitting} otherOpen={otherOpen} toggleOther={toggleOther} picker={picker}
      choose={choose} />
  );
}

// "Other workflow…" stands before "Deny": choosing another workflow is an answer, not a refusal.
function renderProposalAnswers({ title, answers, disabled, submitting, otherOpen, toggleOther, choose }: PendingProposalCardProps) {
  const otherButton = (
    <button
      key="other"
      type="button"
      className="turn-exec-card__decision"
      data-decision-value="other"
      aria-expanded={otherOpen}
      disabled={disabled || submitting !== null}
      onClick={toggleOther ?? undefined}
    >
      {OTHER_WORKFLOW_LABEL}
    </button>
  );

  return answers.flatMap((answer) => [
    ...(answer.value === "skip" ? [otherButton] : []),
    <button
      key={answer.value}
      type="button"
      className="turn-exec-card__decision"
      data-decision-value={answer.value}
      disabled={disabled || submitting !== null}
      onClick={() => void choose(answer.value, `${answer.label}: ${title}`)}
    >
      {submitting === answer.value ? "Sending…" : answer.label}
    </button>,
  ]);
}

type PendingProposalCardProps = {
  title: string;
  reason: string | null | undefined;
  answerable: boolean;
  decided: string | null | undefined;
  answers: readonly ProposalAnswer[];
  disabled: boolean;
  submitting: string | null;
  otherOpen: boolean;
  toggleOther: (() => void) | null;
  picker: ReactNode;
  choose: ReturnType<typeof proposalActions>["choose"];
};

function PendingProposalCard(props: PendingProposalCardProps) {
  const { title, reason, answerable, decided, answers, disabled, submitting, otherOpen, toggleOther, picker, choose } = props;
  return (
    <section
      className="turn-exec-card turn-exec-card--proposal turn-exec-card--attention"
      aria-label="Workflow suggestion"
    >
      <p className="turn-exec-card__reason">
        <strong>{`Run the workflow "${title}"?`}</strong>
        {reason ? ` – ${reason}` : null}
      </p>
      {answerable && !decided ? (
        <div
          className="turn-exec-card__decisions"
          role="group"
          aria-label="Workflow suggestion decision"
        >
          {renderProposalAnswers(props)}
        </div>
      ) : null}
      {answerable && !decided && otherOpen ? picker : null}
      {decided ? (
        <span className="turn-exec-card__muted">
          {decided === "apply" ? "Allowed." : "Denied: continued without the workflow."}
        </span>
      ) : null}
    </section>
  );
}
