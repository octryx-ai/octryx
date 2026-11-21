// The composer's stored draft workflow selection of a fresh thread (carried into the thread once it has its session
// id) and the selection steps of a thread switch. A thread's own selection comes from the server
// (`selectedSession.workflowKey`, the workflow its last turn was sent with).
import type { MutableRefObject } from "react";

import {
  chooseDuringSwitch,
  completeThreadSwitch,
  type ThreadSwitchState,
} from "./threadSwitchSelection";

const WORKFLOW_SELECTION_DRAFT_KEY = "octryx-chat-workflow-key-draft";

export function readDraftSelection(): string {
  try {
    return window.localStorage.getItem(WORKFLOW_SELECTION_DRAFT_KEY) || "";
  } catch {
    return "";
  }
}

export function persistDraftSelection(workflowKey: string) {
  try {
    if (workflowKey) {
      window.localStorage.setItem(WORKFLOW_SELECTION_DRAFT_KEY, workflowKey);
    } else {
      window.localStorage.removeItem(WORKFLOW_SELECTION_DRAFT_KEY);
    }
  } catch {
    // Best-effort only.
  }
}

type RestoreContext = {
  sessionId: string;
  previousSessionIdRef: MutableRefObject<string | null>;
  threadSwitchRef: MutableRefObject<ThreadSwitchState>;
  selectedWorkflowKey: string;
  bootstrapWorkflowKey: string | undefined;
  setSelectedWorkflowKeyState: (workflowKey: string) => void;
};

// Restores the selection of the thread that is now shown, or migrates a fresh thread's draft to its session id.
export function restoreSessionSelection({
  sessionId,
  previousSessionIdRef,
  threadSwitchRef,
  selectedWorkflowKey,
  bootstrapWorkflowKey,
  setSelectedWorkflowKeyState,
}: RestoreContext) {
  const previousSessionId = previousSessionIdRef.current;
  if (sessionId === previousSessionId) {
    return;
  }
  previousSessionIdRef.current = sessionId;
  const userSwitch = threadSwitchRef.current.switching;
  if (!sessionId) {
    const outcome = completeThreadSwitch(threadSwitchRef.current, readDraftSelection());
    threadSwitchRef.current = outcome.state;
    setSelectedWorkflowKeyState(outcome.value);
    if (outcome.persistPick) {
      persistDraftSelection(outcome.value);
    }
    return;
  }
  if (!userSwitch && previousSessionId === "" && selectedWorkflowKey) {
    // Fresh thread got its session id: the draft selection stays with it, and the draft is cleared.
    persistDraftSelection("");
    return;
  }
  const outcome = completeThreadSwitch(threadSwitchRef.current, bootstrapWorkflowKey ?? "");
  threadSwitchRef.current = outcome.state;
  setSelectedWorkflowKeyState(outcome.value);
}

// The mirror changes only when a turn was sent with a selection, or when a
// workflow suggestion was answered ("apply" mirrors the workflow,
// "continue without" mirrors "none"). Follow it for the same thread so the
// composer shows what the thread now runs.
// A thread switch is the restore effect's job: this one follows the mirror
// only while the same thread stays shown.
export function followBootstrapMirror(
  bootstrapSessionIdRef: MutableRefObject<string | null>,
  sessionId: string,
  bootstrapWorkflowKey: string | undefined,
  setSelectedWorkflowKeyState: (workflowKey: string) => void,
) {
  const sameThread = bootstrapSessionIdRef.current === sessionId;
  bootstrapSessionIdRef.current = sessionId;
  if (!sameThread || !sessionId || bootstrapWorkflowKey === undefined) {
    return;
  }
  setSelectedWorkflowKeyState(bootstrapWorkflowKey);
}

// A pick is shown at once; on a fresh thread it is stored as the draft, unless it belongs to a thread switch that is
// still loading. A thread with a session id gets the pick with its next turn.
export function chooseWorkflowKey(
  threadSwitchRef: MutableRefObject<ThreadSwitchState>,
  sessionId: string,
  workflowKey: string,
  setSelectedWorkflowKeyState: (workflowKey: string) => void,
) {
  const outcome = chooseDuringSwitch(threadSwitchRef.current, workflowKey);
  threadSwitchRef.current = outcome.state;
  setSelectedWorkflowKeyState(workflowKey);
  if (!outcome.persistForShownThread) {
    return;
  }
  if (!sessionId) {
    persistDraftSelection(workflowKey);
  }
}
