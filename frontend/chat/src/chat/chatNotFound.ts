// An old or foreign chat link must not open another chat.

export const CHAT_NOT_FOUND_TEXT = "Chat not found. It may have been deleted, or it belongs to someone else.";

export function chatNotFoundNotice(state: { requestedSessionNotFound?: boolean; selectedSession?: unknown } | null | undefined): string {
  return state?.requestedSessionNotFound === true && !state.selectedSession ? CHAT_NOT_FOUND_TEXT : "";
}
