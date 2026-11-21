// A composer selection (a workflow) made while a thread switch
// is still loading belongs to the thread being opened. Without this,
// the choice was persisted to the thread that was still shown and then
// overwritten by the new thread's restore: "New chat" + a quick pick sent the
// turn without the picked workflow.
//
// The owner calls `beginThreadSwitch` when the user starts a navigation to a
// different thread, `chooseDuringSwitch` for every pick, and
// `completeThreadSwitch` once the new thread is shown. A pick made in between
// wins over the restored value and is persisted for the new thread.

export type ThreadSwitchState = {
  switching: boolean;
  // null = no pick while switching; "" is a real pick (the default entry).
  pendingChoice: string | null;
};

export const IDLE_THREAD_SWITCH: ThreadSwitchState = {
  switching: false,
  pendingChoice: null,
};

// A navigation to the thread already shown is no switch: nothing would
// complete it.
export function beginThreadSwitch(
  shownSessionId: string,
  targetSessionId: string,
): ThreadSwitchState {
  return shownSessionId === targetSessionId
    ? IDLE_THREAD_SWITCH
    : { switching: true, pendingChoice: null };
}

export type PickOutcome = {
  state: ThreadSwitchState;
  // Whether the pick is persisted for the shown thread now; while switching
  // it is held for the thread being opened instead.
  persistForShownThread: boolean;
};

export function chooseDuringSwitch(
  state: ThreadSwitchState,
  value: string,
): PickOutcome {
  return state.switching
    ? { state: { switching: true, pendingChoice: value }, persistForShownThread: false }
    : { state, persistForShownThread: true };
}

export type SwitchOutcome = {
  state: ThreadSwitchState;
  value: string;
  // Whether `value` came from a pick during the switch and must be persisted
  // for the new thread.
  persistPick: boolean;
};

export function completeThreadSwitch(
  state: ThreadSwitchState,
  restoredValue: string,
): SwitchOutcome {
  return state.pendingChoice === null
    ? { state: IDLE_THREAD_SWITCH, value: restoredValue, persistPick: false }
    : { state: IDLE_THREAD_SWITCH, value: state.pendingChoice, persistPick: true };
}
