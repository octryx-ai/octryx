// The quiet, optional workflow offer shown next to a turn's answer.
import { useState } from "react";

import type { WorkflowProposalView } from "../../chatDecisionTypes";
import type { TurnWorkflowProposal, WorkflowDecisionChoice } from "./turnExecutionSummary.types";
import { RUN_OFFERED_WORKFLOW } from "./workflowDecisionSend";

// An unasked proposal does not hold the turn. The
// answer comes first; the workflow is a quiet, optional offer next to it.
// Accepting sends the same message again with the workflow selected.
export function WorkflowOffer({
  proposal,
  details,
  disabled,
  onChoose,
  offerPrompt,
}: {
  proposal: TurnWorkflowProposal;
  details: WorkflowProposalView | null | undefined;
  disabled: boolean;
  onChoose?: (choice: WorkflowDecisionChoice) => Promise<void>;
  offerPrompt: string | null;
}) {
  const [submitting, setSubmitting] = useState(false);
  const title = proposal.workflowTitle || proposal.workflowKey || "";
  const sameProposal = Boolean(proposal.proposalId) && details?.proposalId === proposal.proposalId;
  const reason = sameProposal ? details?.reason : null;

  async function run() {
    if (disabled || submitting || !onChoose || !offerPrompt || !proposal.workflowKey) {
      return;
    }
    setSubmitting(true);
    try {
      await onChoose({
        decisionKey: "workflow_offer",
        value: RUN_OFFERED_WORKFLOW,
        label: `Run with workflow: ${title}`,
        workflowKey: proposal.workflowKey,
        prompt: offerPrompt,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="turn-exec-card turn-exec-card--proposal turn-exec-card--neutral" aria-label="Workflow offer">
      <p className="turn-exec-card__reason">
        {`Optional: the workflow "${title}" may fit this request.`}
        {reason ? ` – ${reason}` : null}
      </p>
      {onChoose && offerPrompt ? (
        <div className="turn-exec-card__decisions" role="group" aria-label="Workflow offer">
          <button
            type="button"
            className="turn-exec-card__decision"
            data-decision-value={RUN_OFFERED_WORKFLOW}
            disabled={disabled || submitting}
            onClick={() => void run()}
          >
            {submitting ? "Sending…" : "Run with this workflow"}
          </button>
        </div>
      ) : null}
    </section>
  );
}
