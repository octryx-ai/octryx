// State, derived trace data and the action handlers of one message bubble.
import { useEffect, useState } from "react";

import type { ChatMessage, ToolEvent, TurnTrace } from "../chatThreadTypes";
import { extractPerformanceSections, extractThinkingFromTrace } from "./messageBubbleHelpers";
import { modelDisplayName, modelShortLabel } from "./header/runDetailsFacts";
import { WORKFLOW_START_MODEL } from "./composer/automaticWorkflow";

const UNNAMED_AUTHOR = "Team member";

function resolveUserParticipantTitle(
  currentUserName?: string,
  currentUserEmail?: string,
) {
  return currentUserName?.trim() || currentUserEmail?.trim() || "You";
}

export function participantLabels(
  message: ChatMessage,
  isUser: boolean,
  currentUserName?: string,
  currentUserEmail?: string,
) {
  const assistantRuntimeLabel =
    message.runtimeLabel?.trim() || message.model?.trim() || "AI response";
  // A device answer has no provider name, and its raw model id stood as the author ("Claude-haiku-5-5").
  const assistantParticipantTitle =
    message.providerName?.trim() || modelDisplayName(modelShortLabel(assistantRuntimeLabel));
  // The platform's message that continues a workflow run is the platform's, never under the person's name.
  // A started workflow's link (model "workflow-start") is the platform's message, not a model's answer.
  const fromWorkflow =
    (isUser && message.origin === "workflow") || (!isUser && message.model === WORKFLOW_START_MODEL);
  const participantTitle = fromWorkflow
    ? "Octryx"
    : isUser
    // The author the server recorded; the viewer's own name only for a message not stored yet (no author id),
    // never for a stored author whose name did not resolve.
    ? message.authorName?.trim()
      || (message.authorId ? UNNAMED_AUTHOR : resolveUserParticipantTitle(currentUserName, currentUserEmail))
    : assistantParticipantTitle;
  const participantSupportLabel = fromWorkflow
    ? "Workflow"
    // Design review: the person's own name is enough on their messages; no email under every prompt.
    : isUser
    ? ""
    : !message.providerName?.trim()
      ? "Assistant"
      // The model in words ("Claude Haiku 5.5"), not "BEDROCK / ANTHROPIC.CLAUDE-HAIKU-5-5".
      : modelDisplayName(modelShortLabel(assistantRuntimeLabel));
  return { fromWorkflow, participantTitle, participantSupportLabel };
}

export function useMessageBubbleState(message: ChatMessage) {
  const [speaking, setSpeaking] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceLoading, setTraceLoading] = useState(false);
  const [loadedTurnTrace, setLoadedTurnTrace] = useState<TurnTrace | null>(
    message.turnTrace ?? null,
  );
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const [thinkingLoading, setThinkingLoading] = useState(false);
  const [thinkingUnavailable, setThinkingUnavailable] = useState(false);
  const [performanceOpen, setPerformanceOpen] = useState(false);
  const [performanceLoading, setPerformanceLoading] = useState(false);
  const [performanceUnavailable, setPerformanceUnavailable] = useState(false);
  const [copied, setCopied] = useState(false);
  const [reused, setReused] = useState(false);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    setLoadedTurnTrace(message.turnTrace ?? null);
    setThinkingUnavailable(false);
    setThinkingOpen(false);
    setPerformanceUnavailable(false);
    setPerformanceOpen(false);
  }, [message.turnTrace, message.turnTraceId]);

  return {
    speaking, setSpeaking, traceOpen, setTraceOpen, traceLoading, setTraceLoading, loadedTurnTrace, setLoadedTurnTrace,
    thinkingOpen, setThinkingOpen, thinkingLoading, setThinkingLoading, thinkingUnavailable, setThinkingUnavailable,
    performanceOpen, setPerformanceOpen, performanceLoading, setPerformanceLoading, performanceUnavailable,
    setPerformanceUnavailable, copied, setCopied, reused, setReused, retrying, setRetrying,
  };
}

export type MessageBubbleState = ReturnType<typeof useMessageBubbleState>;

export function messageTraceData(message: ChatMessage, loadedTurnTrace: TurnTrace | null) {
  const effectiveTurnTrace = loadedTurnTrace ?? message.turnTrace ?? null;
  const hasTurnTrace = Boolean(message.turnTraceId || effectiveTurnTrace);
  const thinkingText = extractThinkingFromTrace(effectiveTurnTrace);
  const performance = extractPerformanceSections(
    effectiveTurnTrace,
    message.toolEvents,
  );
  const turnDiff =
    (effectiveTurnTrace?.contextSnapshot?.turn_diff as
      | Record<string, unknown>
      | undefined) ?? null;
  return { effectiveTurnTrace, hasTurnTrace, thinkingText, performance, turnDiff };
}

type ActionInputs = {
  message: ChatMessage;
  displayContent: string;
  actionsDisabled: boolean;
  retryPrompt?: string | null;
  onReuseMessage: (content: string) => void;
  onEditMessage: (messageId: string, content: string) => void;
  onRetryFromMessage: (messageId: string, prompt: string) => Promise<void>;
  onRetryFromToolEvent: (toolCallId: string, prompt: string) => Promise<void>;
  onRetryPrompt: (prompt: string) => Promise<void>;
};

function retryActions(inputs: ActionInputs, state: MessageBubbleState) {
  const { message, actionsDisabled, retryPrompt } = inputs;
  const { retrying, setRetrying } = state;
  // One retry at a time: each variant runs its callback with the turn's prompt.
  async function runRetry(run: (prompt: string) => Promise<void>) {
    if (!retryPrompt || actionsDisabled || retrying) {
      return;
    }
    setRetrying(true);
    try {
      await run(retryPrompt);
    } finally {
      setRetrying(false);
    }
  }
  return {
    triggerRetryPrompt: () => runRetry((prompt) => inputs.onRetryPrompt(prompt)),
    triggerRetryFromHere: () => runRetry((prompt) => inputs.onRetryFromMessage(message.id, prompt)),
    triggerRetryFromToolEvent: (event: ToolEvent) => runRetry((prompt) => inputs.onRetryFromToolEvent(event.id, prompt)),
  };
}

export function messageBubbleActions(inputs: ActionInputs, state: MessageBubbleState) {
  const { message, displayContent, actionsDisabled } = inputs;
  const { speaking, setSpeaking, setCopied, setReused } = state;
  function toggleSpeak() {
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
    } else {
      const utterance = new SpeechSynthesisUtterance(displayContent || "");
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      setSpeaking(true);
      window.speechSynthesis.speak(utterance);
    }
  }
  async function copyMessage() {
    try {
      await navigator.clipboard.writeText(displayContent || "");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Ignore clipboard failures.
    }
  }
  function reuseMessage() {
    inputs.onReuseMessage(message.content || "");
    setReused(true);
    window.setTimeout(() => setReused(false), 1500);
  }
  function startEditMessage() {
    if (actionsDisabled) {
      return;
    }
    inputs.onEditMessage(message.id, message.content || "");
  }
  return { toggleSpeak, copyMessage, reuseMessage, startEditMessage, ...retryActions(inputs, state) };
}
