// A chat's held workflow proposal on the phone (chat parity with the web's start card): the start card of a
// phased workflow (Work item draft, Jira line, steps, where it runs; Start / Other workflow… / Don't start) or the
// plain prompt (Allow once / Always / Other workflow… / Deny). The model is the web's (`workflowStartModel`); the
// workflow list opens in the phone's bottom sheet. After the start, "Open the run" opens the phone's run page.

import { useState } from "react";

import type { WorkflowProposalView } from "../chatDecisionTypes";
import { OTHER_WORKFLOW_LABEL } from "../chat/composer/automaticWorkflow";
import { proposalAnswerBody, proposalAnswerProblem } from "../chat/run/workflowProposalAnswer";
import { answerWorkflowProposal } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { OtherWorkflowSheet } from "./OtherWorkflowSheet";
import { PhoneStartCard } from "./WorkflowStartCardPhone";
import type { PhoneProposal } from "./workflowProposalPhone";


type Props = {
  card: PhoneProposal;
  sessionId: string;
  projectId: string;
  // The chat's state after an answer: the card re-renders from its proposal.
  onAnswered: (proposal: WorkflowProposalView | null | undefined) => void;
  onOpenRun?: (runId: string, title: string) => void;
};

export function WorkflowProposalCard({ card, sessionId, projectId, onAnswered, onOpenRun }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [picking, setPicking] = useState(false);

  const answer = async (decision: string, extra: { runOn?: string; workflowKey?: string; repository?: string; model?: string } = {}) => {
    const body = proposalAnswerBody({ proposalId: card.proposalId, decision, ...extra });
    if (!body || busy) return;
    setBusy(decision);
    setError("");
    try {
      const state = await answerWorkflowProposal(sessionId, body);
      onAnswered(state.selectedSession?.workflowProposal);
      if (decision === "other") setPicking(false);
    } catch (reason) {
      const failure = reason as MobileError;
      const message = proposalAnswerProblem(failure.status ?? 0, failure.detail);
      if (decision === "other") throw new Error(message);
      setError(message);
    } finally {
      setBusy(null);
    }
  };

  const picker = picking ? (
    <OtherWorkflowSheet
      projectId={projectId}
      currentKey={card.workflowKey}
      onClose={() => setPicking(false)}
      onPick={(workflowKey) => answer("other", { workflowKey })}
    />
  ) : null;

  if (card.kind === "plain") {
    return (
      <section className="m-approval m-proposal" aria-label="Workflow suggestion" data-testid="m-workflow-proposal">
        <span className="m-eyebrow">Workflow suggestion</span>
        <h2>{`Run the workflow "${card.title}"?`}</h2>
        {card.reason && <p className="m-muted">{card.reason}</p>}
        {card.decided ? (
          <p className="m-muted">{card.decided === "apply" ? "Allowed." : "Denied: continued without the workflow."}</p>
        ) : (
          <div className="m-buttons">
            {card.answers.map((item) => (
              <button
                key={item.value}
                type="button"
                className={item.value === "apply" ? "m-primary" : undefined}
                disabled={busy !== null}
                onClick={() => void answer(item.value)}
              >
                {busy === item.value ? "Sending…" : item.label}
              </button>
            ))}
            <button type="button" className="m-wide" disabled={busy !== null} onClick={() => setPicking(true)}>
              {OTHER_WORKFLOW_LABEL}
            </button>
          </div>
        )}
        {error && <p className="m-error" role="alert">{error}</p>}
        {picker}
      </section>
    );
  }

  return (
    <PhoneStartCard card={card} projectId={projectId} busy={busy} error={error} onAnswer={answer} onOther={() => setPicking(true)} onOpenRun={onOpenRun}>
      {picker}
    </PhoneStartCard>
  );
}
