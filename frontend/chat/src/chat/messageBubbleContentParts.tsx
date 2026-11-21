// Parts of a chat message: header with actions, diagnostics and tool steps, the bubble, and its footer.
import { Suspense, lazy } from "react";

import { AnswerSourcesButton } from "./evidence/AnswerSourcesButton";
import { ActionMenu } from "../admin/components/workflowSurfaces/ActionMenu";
import { MessageBubbleActions } from "./MessageBubbleActions";
import { MessageBubbleHeader } from "./MessageBubbleHeader";
import { MessageFeedbackBar } from "./messageBubbleFeedback";
import { InlineToolExecutions } from "./messageBubbleInlineTools";
import {
  MessagePerformancePanel,
  MessageThinkingPanel,
} from "./messageBubblePanels";
import { ThinkingDots } from "./messageBubbleIcons";
import type { MessageMenuItem } from "./messageMoreMenu";
import { ToolArtifacts } from "./messageBubbleToolArtifacts";
import { ToolStepFold } from "./ToolStepFold";
import type { MessageBubbleContentProps } from "./messageBubbleContent.types";
import { ContentObligationNotices } from "./run/ContentObligationNotices";
import { TurnExecutionStatusCard } from "./run/TurnExecutionStatusCard";
import { TurnPlanSummary } from "./TurnPlanSummary";
import { WorkflowProposalOptions } from "./run/WorkflowProposalOptions";

const MarkdownRenderer = lazy(async () => ({
  default: (await import("./MarkdownRenderer")).MarkdownRenderer,
}));
const ToolEventList = lazy(async () => ({
  default: (await import("./traceToolEventList")).ToolEventList,
}));
const TurnDiffSummary = lazy(async () => ({
  default: (await import("./turnDiffSummary")).TurnDiffSummary,
}));
const TurnTraceModal = lazy(async () => ({
  default: (await import("./traceTurnTraceModal")).TurnTraceModal,
}));

type Props = MessageBubbleContentProps & { repeatsTurnContext: boolean; intermediateToolStep: boolean };

export function BubbleHeader({ props, menuItems }: { props: Props; menuItems: MessageMenuItem[] }) {
  const {
    isUser, isThinking, toolOnlyAssistant, displayContent, participantTitle, participantSupportLabel, timestamp,
    copied, copyMessage, actionsDisabled, startEditMessage, reused, reuseMessage, retryPrompt, retrying,
    triggerRetryFromHere, hasTurnTrace,
  } = props;
  const showsActions = (isUser || !isThinking) && !toolOnlyAssistant && Boolean(displayContent);
  return (
    <MessageBubbleHeader
      isUser={isUser}
      title={participantTitle}
      roleLabel={participantSupportLabel}
      timestamp={timestamp}
      headerActions={
        showsActions ? (
          <MessageBubbleActions
            compact
            iconOnly
            isUser={isUser}
            isThinking={isThinking}
            displayContent={displayContent}
            copied={copied}
            copyMessage={copyMessage}
            actionsDisabled={actionsDisabled}
            startEditMessage={startEditMessage}
            reused={reused}
            reuseMessage={reuseMessage}
            retryPrompt={retryPrompt}
            retrying={retrying}
            triggerRetryFromHere={triggerRetryFromHere}
            menuItems={menuItems}
          />
        ) : !isUser && hasTurnTrace ? (
          // A tool-only or still-thinking turn keeps its diagnostics in the same menu.
          <ActionMenu row={{ objectName: "this answer" }} items={menuItems} />
        ) : null
      }
    />
  );
}

function BubbleWorkflowNotes({ props }: { props: Props }) {
  const {
    isUser, executionSummary, workflowProposal, actionsDisabled, onWorkflowDecision, repeatsTurnContext, retryPrompt,
    workflowOptions,
  } = props;
  return (
    <>
      {!isUser &&
      executionSummary.status === "ready" &&
      executionSummary.summary.workflowProposal ? (
        <WorkflowProposalOptions
          proposal={executionSummary.summary.workflowProposal}
          details={workflowProposal}
          disabled={actionsDisabled}
          onChoose={onWorkflowDecision}
          repeatsTurn={repeatsTurnContext}
          offerPrompt={retryPrompt}
          workflowOptions={workflowOptions}
        />
      ) : null}
      {!isUser && executionSummary.status === "ready" ? (
        <ContentObligationNotices notices={executionSummary.summary.contentObligations} />
      ) : null}
    </>
  );
}

export function BubbleDiagnostics({ props }: { props: Props }) {
  const {
    message, isUser, hasTurnTrace, thinkingOpen, thinkingText, thinkingUnavailable, toggleThinking, performanceOpen,
    performance, performanceUnavailable, triggerRetryFromToolEvent, onPreviewArtifact, actionsDisabled, retrying,
    turnDiff, setTraceOpen,
  } = props;
  return (
    <>
      <MessageThinkingPanel
        isUser={isUser}
        hasTurnTrace={hasTurnTrace}
        thinkingOpen={thinkingOpen}
        thinkingText={thinkingText}
        thinkingUnavailable={thinkingUnavailable}
        onToggleThinking={toggleThinking}
      />
      <MessagePerformancePanel
        isUser={isUser}
        performanceOpen={performanceOpen}
        performance={performance}
        performanceUnavailable={performanceUnavailable}
      />
      {!isUser ? (
        <ToolStepFold events={message.toolEvents}>
          <Suspense fallback={null}>
            <ToolEventList
              events={message.toolEvents}
              compact
              onRetryFromToolEvent={(event) =>
                void triggerRetryFromToolEvent(event)
              }
              onPreviewArtifact={onPreviewArtifact}
              actionsDisabled={actionsDisabled || retrying}
            />
          </Suspense>
        </ToolStepFold>
      ) : null}
      {!isUser ? <TurnPlanSummary events={message.toolEvents} /> : null}
      {!isUser ? (
        <Suspense fallback={null}>
          <TurnDiffSummary turnDiff={turnDiff} onOpen={setTraceOpen} />
        </Suspense>
      ) : null}
      <BubbleWorkflowNotes props={props} />
    </>
  );
}

export function BubbleBody({ props, hasInlineToolEvents }: { props: Props; hasInlineToolEvents: boolean }) {
  const { message, isUser, isThinking, displayContent, theme } = props;
  return (
    <div
      className={`message-bubble ${isUser ? "message-bubble--user" : "message-bubble--assistant"} ${isThinking ? "message-bubble--thinking" : ""}`}
    >
      {isThinking ? (
        <div className="thinking-card">
          <ThinkingDots />
          <div className="thinking-card__text">
            {message.content || "Working through the configured systems..."}
          </div>
        </div>
      ) : displayContent ? (
        <Suspense
          fallback={
            <div className="message-bubble__empty">
              Rendering message...
            </div>
          }
        >
          <MarkdownRenderer content={displayContent} theme={theme} />
        </Suspense>
      ) : !hasInlineToolEvents ? (
        <div className="message-bubble__empty">Tool execution</div>
      ) : null}
    </div>
  );
}

export function BubbleFooter({ props }: { props: Props }) {
  const {
    message, isUser, isThinking, toolOnlyAssistant, displayContent, executionSummary, retryExecutionSummary,
    hasTurnTrace, openTrace, traceLoading, onWorkflowDecision, actionsDisabled, referencedArtifacts, onPreviewArtifact,
    intermediateToolStep, effectiveTurnTrace, feedbackDisabled, onSubmitFeedback, traceOpen,
    setTraceClosed, loadTurnTrace,
  } = props;
  return (
    <>
      <TurnExecutionStatusCard
        load={executionSummary}
        onRetry={retryExecutionSummary}
        onOpenDetails={hasTurnTrace ? () => void openTrace() : undefined}
        detailsLoading={traceLoading}
        onWorkflowDecision={onWorkflowDecision}
        decisionsDisabled={actionsDisabled}
      />
      {!isUser && referencedArtifacts && referencedArtifacts.length ? (
        <div className="message-artifact-references">
          <ToolArtifacts
            artifacts={referencedArtifacts}
            onPreviewArtifact={onPreviewArtifact}
          />
        </div>
      ) : null}
      <InlineToolExecutions
        events={message.toolEvents}
        onPreviewArtifact={onPreviewArtifact}
      />
      {!isUser && !toolOnlyAssistant ? (
        <div className="message-row__footer message-row__footer--assistant">
          <div className="message-row__footer-main">
            {!isThinking && displayContent ? <AnswerSourcesButton key={message.turnTraceId || message.id} contentKey={displayContent}
              quietWhenNone={intermediateToolStep} /> : null}
            <MessageFeedbackBar
              message={message}
              disabled={feedbackDisabled}
              onSubmitFeedback={onSubmitFeedback}
              iconOnly
            />
          </div>
        </div>
      ) : null}
      {effectiveTurnTrace ? (
        <Suspense fallback={null}>
          <TurnTraceModal
            trace={effectiveTurnTrace}
            open={traceOpen}
            onClose={setTraceClosed}
            executionSummary={executionSummary}
            onRetryExecutionSummary={retryExecutionSummary}
            loadTrace={loadTurnTrace}
          />
        </Suspense>
      ) : null}
    </>
  );
}
