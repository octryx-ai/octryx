// Reads behind the chat bootstrap: the session view, the listed-thread check and the performance debug flag.
import type { ChatState } from "../types";
import { sessionViewPath, type SessionView } from "./sessionView";

export function threadListed(groups: ChatState["activeThreadGroups"] | null | undefined, sessionId: string): boolean {
  return (groups ?? []).some((group) => (group.sessions ?? []).some((thread) =>
    thread.id === sessionId || (thread.subThreads ?? []).some((sub) => sub.id === sessionId)));
}

/** The session view, or null when this server has none (404/405) or the read fails: then the bootstrap loads. */
export async function readSessionView(sessionId: string): Promise<SessionView | null> {
  try {
    const response = await fetch(sessionViewPath(sessionId), {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as unknown;
    return payload && typeof payload === "object" ? (payload as SessionView) : null;
  } catch {
    return null;
  }
}

export function isChatPerformanceDebugEnabled() {
  try {
    return window.localStorage.getItem("octryx-chat-debug-performance") === "1";
  } catch {
    return false;
  }
}
