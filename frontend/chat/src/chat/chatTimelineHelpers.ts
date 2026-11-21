import type { ChatMessage } from "../chatThreadTypes";

function isAssistantMessage(message: ChatMessage) {
  return (
    String(message.role || "")
      .trim()
      .toLowerCase() === "assistant"
  );
}

function trimmedIdentityPart(value: string | null | undefined) {
  return String(value || "").trim();
}

function sameAssistantIdentity(left: ChatMessage, right: ChatMessage) {
  return (
    trimmedIdentityPart(left.providerName) ===
      trimmedIdentityPart(right.providerName) &&
    trimmedIdentityPart(left.runtimeLabel) ===
      trimmedIdentityPart(right.runtimeLabel) &&
    trimmedIdentityPart(left.model) === trimmedIdentityPart(right.model)
  );
}

export function isToolOnlyAssistantMessage(message: ChatMessage) {
  return (
    isAssistantMessage(message) &&
    !(message.content || "").trim() &&
    (message.toolEvents?.length ?? 0) > 0
  );
}

export function isRedundantAssistantPlaceholderMessage(message: ChatMessage) {
  return (
    isAssistantMessage(message) &&
    !(message.content || "").trim() &&
    (message.toolEvents?.length ?? 0) === 0
  );
}

function mergeToolOnlyAssistantMessages(
  left: ChatMessage,
  right: ChatMessage,
): ChatMessage {
  return {
    ...left,
    toolEvents: [...(left.toolEvents ?? []), ...(right.toolEvents ?? [])],
    turnTrace: right.turnTrace ?? left.turnTrace,
    turnTraceId: right.turnTraceId ?? left.turnTraceId,
    feedback: right.feedback ?? left.feedback,
  };
}

export function normalizeTranscriptMessages(messages: ChatMessage[]) {
  const normalized: ChatMessage[] = [];

  for (const message of messages) {
    if (isRedundantAssistantPlaceholderMessage(message)) {
      continue;
    }

    const previous = normalized.at(-1);
    if (
      previous &&
      isToolOnlyAssistantMessage(previous) &&
      isToolOnlyAssistantMessage(message) &&
      sameAssistantIdentity(previous, message)
    ) {
      normalized[normalized.length - 1] = mergeToolOnlyAssistantMessages(
        previous,
        message,
      );
      continue;
    }

    normalized.push(message);
  }

  return normalized;
}
