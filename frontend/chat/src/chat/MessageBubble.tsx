import type { ComponentProps } from "react";
import type { MessageFeedbackPayload } from "./messageFeedbackModel";

import type { ChatMessage, ToolArtifact, TurnTrace } from "../chatThreadTypes";
import type { WorkflowOption } from "../chatOptionTypes";
import type { WorkflowProposalView } from "../chatDecisionTypes";
import { formatMessageTimestamp } from "./messageBubbleHelpers";
import { isToolOnlyAssistantMessage } from "./chatTimelineHelpers";
import { MessageBubbleContent } from "./messageBubbleContent";
import type { WorkflowDecisionChoice } from "./run/turnExecutionSummary.types";
import { useTurnExecutionSummary } from "./run/useTurnExecutionSummary";
import { turnTraceToggles } from "./messageBubbleTraceToggles";
import {
  messageBubbleActions,
  messageTraceData,
  participantLabels,
  useMessageBubbleState,
  type MessageBubbleState,
} from "./messageBubbleState";

type MessageBubbleProps = {
  message: ChatMessage;
  currentUserName?: string;
  currentUserEmail?: string;
  feedbackDisabled: boolean;
  onSubmitFeedback: (messageId: string, payload: MessageFeedbackPayload) => Promise<void>;
  onReuseMessage: (content: string) => void;
  onEditMessage: (messageId: string, content: string) => void;
  onRetryFromMessage: (messageId: string, prompt: string) => Promise<void>;
  onRetryFromToolEvent: (toolCallId: string, prompt: string) => Promise<void>;
  onRetryPrompt: (prompt: string) => Promise<void>;
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
  onLoadTurnTrace?: (traceId: string) => Promise<TurnTrace | null>;
  onWorkflowDecision?: (choice: WorkflowDecisionChoice) => Promise<void>;
  workflowProposal?: WorkflowProposalView | null;
  // The composer's workflow catalog ("Other workflow…" on a pending proposal).
  workflowOptions?: readonly WorkflowOption[];
  /** A later message of the same turn (see `run/workflowTurnContext.ts`). */
  repeatsTurnContext?: boolean;
  /** A tool step followed by the turn's answer (see `evidence/intermediateToolMessages.ts`). */
  intermediateToolStep?: boolean;
  referencedArtifacts?: ToolArtifact[];
  retryPrompt?: string | null;
  actionsDisabled: boolean;
  theme: "dark" | "light";
};

type ContentProps = ComponentProps<typeof MessageBubbleContent>;

// The platform's own git turn of a team run is stored as a user turn; it is a note from Octryx, not the
// person's message (origin "platform", from the turn's idempotency key). The stored prompt stays in the tooltip.
function MessagePlatformNote({ message, timestamp }: { message: ChatMessage; timestamp: string }) {
  return (
    <div className="message-platform-note" data-testid="message-platform-note" title={message.content}>
      <span className="message-platform-note__author">Octryx</span>
      <span>Git work for the run's items: worktrees and merges</span>
      {timestamp ? <time className="message-platform-note__time">{timestamp}</time> : null}
    </div>
  );
}

function stateContentProps(state: MessageBubbleState) {
  return {
    thinkingOpen: state.thinkingOpen,
    thinkingLoading: state.thinkingLoading,
    performanceOpen: state.performanceOpen,
    performanceLoading: state.performanceLoading,
    traceLoading: state.traceLoading,
    thinkingUnavailable: state.thinkingUnavailable,
    performanceUnavailable: state.performanceUnavailable,
    setTraceOpen: () => state.setTraceOpen(true),
    retrying: state.retrying,
    copied: state.copied,
    reused: state.reused,
    speaking: state.speaking,
    traceOpen: state.traceOpen,
    setTraceClosed: () => state.setTraceOpen(false),
  };
}

function passedContentProps(props: MessageBubbleProps) {
  const { message, onLoadTurnTrace } = props;
  return {
    theme: props.theme,
    referencedArtifacts: props.referencedArtifacts,
    onPreviewArtifact: props.onPreviewArtifact,
    feedbackDisabled: props.feedbackDisabled,
    onSubmitFeedback: props.onSubmitFeedback,
    actionsDisabled: props.actionsDisabled,
    retryPrompt: props.retryPrompt,
    loadTurnTrace: onLoadTurnTrace,
    onWorkflowDecision: props.onWorkflowDecision,
    workflowProposal: props.workflowProposal,
    workflowOptions: props.workflowOptions,
    repeatsTurnContext: props.repeatsTurnContext ?? false,
  };
}

export function MessageBubble(props: MessageBubbleProps) {
  const { message, intermediateToolStep = false } = props;
  const isUser = message.role === "user";
  const isThinking = message.id === "pending-assistant-message";
  const timestamp = formatMessageTimestamp(message.createdAt);
  const { fromWorkflow, participantTitle, participantSupportLabel } = participantLabels(
    message, isUser, props.currentUserName, props.currentUserEmail);
  const displayContent = message.content || "";
  const toolOnlyAssistant = isToolOnlyAssistantMessage(message);
  // Only an explicit server-provided trace id links a message to its summary.
  // Tool-only turns are included: approval/clarification pauses end on one.
  const executionSummary = useTurnExecutionSummary(
    !isUser && !isThinking ? message.turnTraceId : null,
  );
  const state = useMessageBubbleState(message);
  const trace = messageTraceData(message, state.loadedTurnTrace);
  const actions = messageBubbleActions({ ...props, displayContent }, state);
  const { openTrace, toggleThinking, togglePerformance } = turnTraceToggles({
    ...state, ...trace, message, onLoadTurnTrace: props.onLoadTurnTrace,
  });

  if (isUser && message.origin === "platform") {
    return <MessagePlatformNote message={message} timestamp={timestamp} />;
  }

  const contentProps: ContentProps = {
    ...stateContentProps(state), ...passedContentProps(props), ...trace, ...actions,
    message, isUser, isThinking, timestamp, participantTitle, participantSupportLabel, toolOnlyAssistant,
    toggleThinking, togglePerformance, openTrace, displayContent,
    executionSummary: executionSummary.load,
    retryExecutionSummary: executionSummary.retry,
    /* The platform's own workflow-start message cites nothing by design: no "Sources · none cited". */
    intermediateToolStep: intermediateToolStep || fromWorkflow,
  };
  return <MessageBubbleContent {...contentProps} />;
}
