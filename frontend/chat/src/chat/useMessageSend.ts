import type { WorkflowDecisionChoice } from "./run/turnExecutionSummary.types";
import {
  buildWorkflowDecisionSend,
  buildOfferedWorkflowSend,
  buildWorkflowProposalDecision,
  type MessageSendOptions,
} from "./run/workflowDecisionSend";
import {
  answerWorkflowProposal as answerProposal,
  sendMessage,
  type MessageSendArgs,
  type WorkflowProposalDecision,
} from "./messageSendActions";

export function useMessageSend(args: MessageSendArgs) {
  const { selectedSession, setEditingMessage } = args;

  const handleSend = async (
    overridePrompt?: string,
    sendOptions?: MessageSendOptions,
  ) => sendMessage(args, overridePrompt, sendOptions);

  const answerWorkflowProposal = async (
    decision: WorkflowProposalDecision,
    inline = false,
  ) => answerProposal(args, decision, inline);

  // A decision button on a workflow clarification sends its closed value as
  // `workflow_decisions` with the next message.
  const handleWorkflowDecision = async (choice: WorkflowDecisionChoice) => {
    const proposalDecision = buildWorkflowProposalDecision(
      selectedSession?.id,
      choice,
    );
    if (proposalDecision) {
      await answerWorkflowProposal(proposalDecision, choice.inline === true);
      return;
    }
    const offered = buildOfferedWorkflowSend(choice);
    if (offered) {
      setEditingMessage(null);
      await handleSend(offered.prompt, offered.options);
      return;
    }
    const { prompt, options } = buildWorkflowDecisionSend(choice);
    setEditingMessage(null);
    await handleSend(prompt, options);
  };

  return { handleSend, handleWorkflowDecision };
}
