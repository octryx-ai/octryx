// An old or foreign chat link must not open another chat. The bootstrap answers
// `requestedSessionNotFound` instead; the page says so in one sentence.

export const CHAT_NOT_FOUND_TEXT = "Chat not found. It may have been deleted, or it belongs to someone else.";

/** The notice for a requested chat this person cannot open; empty when a chat is open or none was asked for. */
export function chatNotFoundNotice(state: { requestedSessionNotFound?: boolean; selectedSession?: unknown } | null | undefined): string {
  return state?.requestedSessionNotFound === true && !state.selectedSession ? CHAT_NOT_FOUND_TEXT : "";
}
