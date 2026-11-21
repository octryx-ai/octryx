// Stop and continue handlers of a chat session: the coordinator path when it applies, else the session endpoint.
// A failed coordinator status request is shown to the user; it never switches to the session endpoint.
import type { ChatState } from "../types";
import type { CoordinatorStateContract } from "../chatCoordinatorTypes";
import { buildChatSearch } from "./appHelpers";
import { readJson } from "./chatApiClient";
import {
  applySessionCoordinatorStop,
  applySessionCoordinatorContinue,
  describeCoordinatorStopBlockedState,
  describeCoordinatorContinueBlockedState,
  loadSessionCoordinatorStatus,
  shouldUseCoordinatorStop,
  shouldUseCoordinatorContinue,
} from "./sessionCoordinatorClient";
import type { UseSessionActionsArgs } from "./useSessionActions.types";

// Applies a coordinator stop or continue and reloads the coordinator's root session.
async function runCoordinatorControl(
  { setSending, setError, loadState }: UseSessionActionsArgs,
  sessionId: string,
  apply: typeof applySessionCoordinatorStop,
  fallback: string,
) {
  setSending(true);
  try {
    const controlResponse = await apply(sessionId);
    const search = buildChatSearch({
      sessionId: controlResponse.contract.root_session_id || sessionId,
    });
    await loadState(search, { preserveTrace: true });
  } catch (controlError) {
    setError(controlError instanceof Error ? controlError.message : fallback);
  } finally {
    setSending(false);
  }
}

// Loads the coordinator contract; on failure shows the server's error and returns null.
async function loadCoordinatorContract(
  { setError }: UseSessionActionsArgs,
  sessionId: string,
): Promise<CoordinatorStateContract | null> {
  try {
    return await loadSessionCoordinatorStatus(sessionId);
  } catch (statusError) {
    setError(
      statusError instanceof Error
        ? statusError.message
        : "Failed to load coordinator status",
    );
    return null;
  }
}

async function stopThroughSession(
  { setError, applyState }: UseSessionActionsArgs,
  sessionId: string,
) {
  try {
    const nextState = await readJson<ChatState>(
      `/chat/api/sessions/${sessionId}/stop`,
      {
        method: "POST",
        body: JSON.stringify({}),
      },
    );
    const search = buildChatSearch({
      sessionId: nextState.selectedSession?.id ?? null,
    });
    applyState(nextState, search, { preserveTrace: true });
  } catch (stopError) {
    setError(
      stopError instanceof Error
        ? stopError.message
        : "Failed to stop thread",
    );
  }
}

async function continueThroughSession(
  {
    selectedRuntimeTargetId,
    selectedThinkingLevel,
    setSending,
    setError,
    applyState,
  }: UseSessionActionsArgs,
  sessionId: string,
) {
  setSending(true);
  try {
    const nextState = await readJson<ChatState>(
      `/chat/api/sessions/${sessionId}/continue`,
      {
        method: "POST",
        body: JSON.stringify({
          runtime_target_id: selectedRuntimeTargetId,
          thinking_level: selectedThinkingLevel,
        }),
      },
    );
    const search = buildChatSearch({
      sessionId: nextState.selectedSession?.id ?? sessionId,
      projectId: nextState.selectedProjectId,
      runtimeTargetId: nextState.selectedRuntimeTargetId,
      agentId: nextState.selectedAgentId,
      agentType: nextState.selectedAgentType,
    });
    applyState(nextState, search);
  } catch (continueError) {
    setError(
      continueError instanceof Error
        ? continueError.message
        : "Failed to continue thread",
    );
  } finally {
    setSending(false);
  }
}

async function stopSession(args: UseSessionActionsArgs) {
  const { selectedSession, selectedSessionIsRunning, setError } = args;
  if (!selectedSession || !selectedSessionIsRunning) {
    return;
  }
  setError(null);
  const coordinatorContract = await loadCoordinatorContract(args, selectedSession.id);
  if (!coordinatorContract) {
    return;
  }
  if (shouldUseCoordinatorStop(coordinatorContract, selectedSession.id)) {
    if (!coordinatorContract.can_stop) {
      setError(describeCoordinatorStopBlockedState(coordinatorContract));
      return;
    }
    await runCoordinatorControl(args, selectedSession.id, applySessionCoordinatorStop,
      "Failed to stop coordinator session");
    return;
  }
  await stopThroughSession(args, selectedSession.id);
}

async function continueSession(args: UseSessionActionsArgs) {
  const { selectedSession, selectedSessionIsRunning, selectedSessionIsArchived, setError } = args;
  if (
    !selectedSession ||
    selectedSessionIsRunning ||
    selectedSessionIsArchived
  ) {
    return;
  }
  setError(null);
  const coordinatorContract = await loadCoordinatorContract(args, selectedSession.id);
  if (!coordinatorContract) {
    return;
  }
  if (shouldUseCoordinatorContinue(coordinatorContract)) {
    if (!coordinatorContract.can_continue) {
      setError(describeCoordinatorContinueBlockedState(coordinatorContract));
      return;
    }
    await runCoordinatorControl(args, selectedSession.id, applySessionCoordinatorContinue,
      "Failed to continue coordinator session");
    return;
  }
  await continueThroughSession(args, selectedSession.id);
}

export function createSessionRunControlHandlers(args: UseSessionActionsArgs) {
  const handleStop = async () => stopSession(args);
  const handleContinue = async () => continueSession(args);
  return { handleStop, handleContinue };
}
