// One timeline row of the primary workspace: a message bubble or an approval bubble.
import { MessageBubble } from "./MessageBubble";
import { ApprovalBubble } from "./ApprovalBubble";

export function renderWorkspaceTimelineItem(
  item: any,
  props: any,
  repeatedTurnMessages: Set<string>,
  intermediateToolMessages: Set<string>,
) {
  const {
    selectedSession, chatState, selectedSessionIsRunning, currentUserName, currentUserEmail,
    referencedArtifactsByMessageId, sending, handleSubmitMessageFeedback, handleReuseMessage,
    handleEditMessage, handleRetryFromMessage, handleRetryFromToolEvent, handleRetryPrompt,
    handleWorkflowDecision, setPreviewArtifact, loadTurnTrace, assistantRetryPromptByMessageId,
    composerDisabled, approvalRetryPromptById, handleApprovalDecision, handleRetryFromApproval,
    handleRetryFromChangePreview, chatTheme, workflowOptions,
  } = props;
  return item.kind === "message" ? (
    <MessageBubble
      key={item.id}
      message={item.message}
      currentUserName={currentUserName}
      currentUserEmail={currentUserEmail}
      referencedArtifacts={
        referencedArtifactsByMessageId.get(item.message.id) ?? []
      }
      feedbackDisabled={
        sending ||
        selectedSessionIsRunning ||
        !selectedSession ||
        chatState?.selectedSessionIsArchived
      }
      onSubmitFeedback={handleSubmitMessageFeedback}
      onReuseMessage={handleReuseMessage}
      onEditMessage={handleEditMessage}
      onRetryFromMessage={handleRetryFromMessage}
      onRetryFromToolEvent={handleRetryFromToolEvent}
      onRetryPrompt={handleRetryPrompt}
      onWorkflowDecision={handleWorkflowDecision}
      workflowProposal={selectedSession?.workflowProposal ?? null}
      workflowOptions={workflowOptions}
      repeatsTurnContext={repeatedTurnMessages.has(item.message.id)}
      intermediateToolStep={intermediateToolMessages.has(item.message.id)}
      onPreviewArtifact={setPreviewArtifact}
      onLoadTurnTrace={loadTurnTrace}
      retryPrompt={assistantRetryPromptByMessageId.get(
        item.message.id,
      )}
      actionsDisabled={composerDisabled}
      theme={chatTheme}
    />
  ) : (
    <ApprovalBubble
      key={item.id}
      approval={item.approval}
      retryPrompt={
        approvalRetryPromptById.get(item.approval.id) ?? null
      }
      actionsDisabled={composerDisabled}
      canGrantStandingConfirmation={
        selectedSession?.canGrantStandingConfirmation === true
      }
      currentUserId={chatState?.currentUser?.id ?? null}
      onDecision={(
        approval: any,
        decision: "approve" | "reject" | "always",
      ) => void handleApprovalDecision(approval, decision)}
      onRetryFromApproval={handleRetryFromApproval}
      onRetryFromChangePreview={handleRetryFromChangePreview}
    />
  );
}
