import type { ChatState } from "../types";
import type { ThreadGroup } from "../chatThreadTypes";
import { chatApiPath } from "./chatApiClient";

export type SessionView = Partial<ChatState> & { requestedSessionNotFound?: boolean };

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

// The view answers 0 for the thread number, so it comes from the list.
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
