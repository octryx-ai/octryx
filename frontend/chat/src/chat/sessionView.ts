// Switching chats without reloading the whole bootstrap (backend). A switch to an existing
// chat reads GET /chat/api/sessions/{id}/view: only the selected session's part of the state. The thread list,
// projects, agent options and branding stay from the first bootstrap. Pure functions; the hook owns the request.
import type { ChatState } from "../types";
import type { ThreadGroup } from "../chatThreadTypes";
import { chatApiPath } from "./chatApiClient";

/** The fields the view answers; everything else in the chat state stays as it is. */
export type SessionView = Partial<ChatState> & { requestedSessionNotFound?: boolean };

/** The session a plain switch (`?session_id=<id>` and nothing else) opens; null for any other address. */
export function sessionSwitchTarget(search: string): string | null {
  let params: URLSearchParams;
  try {
    params = new URLSearchParams(search);
  } catch {
    return null;
  }
  const keys = Array.from(params.keys());
  if (keys.length !== 1 || keys[0] !== "session_id") return null;
  const id = (params.get("session_id") || "").trim();
  return id || null;
}

export function sessionViewPath(sessionId: string): string {
  return chatApiPath(`/sessions/${encodeURIComponent(sessionId)}/view`);
}

function listThreadNumber(groups: ThreadGroup[] | null | undefined, sessionId: string): number | undefined {
  for (const group of groups ?? []) {
    const match = (group.sessions ?? []).find((thread) => thread.id === sessionId);
    if (match?.threadNumber) return match.threadNumber;
  }
  return undefined;
}

/**
 * The view as a next state for the bootstrap merge: lists are left out (the merge keeps the previous ones), the
 * thread number comes from the list (the view answers 0), a null Workspace keeps the current one, and a switch to
 * an existing chat is never a new-chat draft.
 */
export function viewToState(view: SessionView, previous: ChatState): ChatState {
  const session = view.selectedSession ?? null;
  const threadNumber = session
    ? (session.threadNumber && session.threadNumber > 0
      ? session.threadNumber
      : listThreadNumber(previous.activeThreadGroups, session.id)
        ?? (previous.selectedSession?.id === session.id ? previous.selectedSession.threadNumber : undefined))
    : undefined;
  return {
    ...(view as ChatState),
    selectedSession: session ? { ...session, threadNumber } : null,
    selectedWorkspace: view.selectedWorkspace ?? previous.selectedWorkspace ?? null,
    newThread: false,
  };
}
