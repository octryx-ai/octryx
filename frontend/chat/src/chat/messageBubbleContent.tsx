import { hasInlineToolExecutionEvents } from "./messageBubbleInlineTools.helpers";
import { MessageBubbleAvatar } from "./MessageBubbleHeader";
import { assistantMessageMenuItems } from "./messageMoreMenu";
import type { MessageBubbleContentProps } from "./messageBubbleContent.types";
import { BubbleBody, BubbleDiagnostics, BubbleFooter, BubbleHeader } from "./messageBubbleContentParts";

export function MessageBubbleContent(input: MessageBubbleContentProps) {
  const props = {
    ...input,
    repeatsTurnContext: input.repeatsTurnContext ?? false,
    intermediateToolStep: input.intermediateToolStep ?? false,
  };
  const { message, isUser, toolOnlyAssistant, participantTitle } = props;
  const hasInlineToolEvents = hasInlineToolExecutionEvents(message.toolEvents);
  const menuItems = isUser ? [] : assistantMessageMenuItems({
    retryPrompt: props.retryPrompt, retrying: props.retrying, actionsDisabled: props.actionsDisabled,
    triggerRetryPrompt: props.triggerRetryPrompt, speaking: props.speaking, toggleSpeak: props.toggleSpeak,
    hasTurnTrace: props.hasTurnTrace, thinkingOpen: props.thinkingOpen, thinkingLoading: props.thinkingLoading,
    toggleThinking: props.toggleThinking, performanceOpen: props.performanceOpen,
    performanceLoading: props.performanceLoading, togglePerformance: props.togglePerformance,
    traceLoading: props.traceLoading, openTrace: props.openTrace,
  });

  return (
    <article
      className={`message-row ${isUser ? "message-row--user" : "message-row--assistant"} ${toolOnlyAssistant ? "message-row--tool-only" : ""}`}
    >
      <MessageBubbleAvatar isUser={isUser} title={participantTitle} />
      <div
        className={`message-row__content ${isUser ? "message-row__content--user" : "message-row__content--assistant"}`}
      >
        <BubbleHeader props={props} menuItems={menuItems} />
        <BubbleDiagnostics props={props} />
        <BubbleBody props={props} hasInlineToolEvents={hasInlineToolEvents} />
        <BubbleFooter props={props} />
      </div>
    </article>
  );
}
