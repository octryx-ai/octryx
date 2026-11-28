// A pick made while a thread switch loads belongs to the new thread, else the new thread's restore overwrites it.

export type ThreadSwitchState = {
  switching: boolean;
  // null = no pick while switching; "" is a real pick (the default entry).
  pendingChoice: string | null;
};

export const IDLE_THREAD_SWITCH: ThreadSwitchState = {
  switching: false,
  pendingChoice: null,
};

// A navigation to the thread already shown is no switch: nothing would complete it.
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
