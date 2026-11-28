// styles/chat/chat-compact-shell.css must use the same pixel values; a unit test asserts it.

export const CHAT_LAYOUT_BREAKPOINTS = {
  phoneMaxWidth: 720,
  compactMaxWidth: 980,
} as const;

export type ChatLayoutMode = "phone" | "compact" | "desktop";

export const CHAT_LAYOUT_MEDIA_QUERIES = {
  phone: `(max-width: ${CHAT_LAYOUT_BREAKPOINTS.phoneMaxWidth}px)`,
  compact: `(max-width: ${CHAT_LAYOUT_BREAKPOINTS.compactMaxWidth}px)`,
} as const;

export function resolveChatLayoutMode(viewportWidth: number): ChatLayoutMode {
  if (!Number.isFinite(viewportWidth)) {
    return "desktop";
  }
  if (viewportWidth <= CHAT_LAYOUT_BREAKPOINTS.phoneMaxWidth) {
    return "phone";
  }
  if (viewportWidth <= CHAT_LAYOUT_BREAKPOINTS.compactMaxWidth) {
    return "compact";
  }
  return "desktop";
}

export function isCompactChatLayout(mode: ChatLayoutMode): boolean {
  return mode === "phone" || mode === "compact";
}
