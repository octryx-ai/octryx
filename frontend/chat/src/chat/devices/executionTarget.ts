import { useSyncExternalStore } from "react";

// Where a chat message runs: the Server (today's behaviour) or one of the sender's own devices. The
// choice is sticky per thread; a new thread's choice moves to the thread once the first send created it.
// A device target's `model` is one of the profile's `/model` rows; empty or absent: the device's default.

export type DeviceProfile = "governed" | "seat";
export type ExecutionTarget =
  | { kind: "server" }
  | {
      kind: "device";
      deviceId: string;
      folder: string;
      profile: DeviceProfile;
      model?: string;
      // Claude Code's permission mode and effort for this turn (empty: the device's default).
      permissionMode?: string;
      effort?: string;
    };

export const SERVER_TARGET: ExecutionTarget = { kind: "server" };
const NEW_THREAD = "__new__";
const targets = new Map<string, ExecutionTarget>();
const listeners = new Set<() => void>();

const key = (sessionId: string | null | undefined) => sessionId || NEW_THREAD;
const notify = () => listeners.forEach((listener) => listener());

export function readExecutionTarget(sessionId: string | null | undefined): ExecutionTarget {
  return targets.get(key(sessionId)) ?? SERVER_TARGET;
}

export function hasExecutionTarget(sessionId: string | null | undefined): boolean {
  return targets.has(key(sessionId));
}

export function setExecutionTarget(sessionId: string | null | undefined, target: ExecutionTarget) {
  targets.set(key(sessionId), target);
  notify();
}

/** After the first send of a new thread: the thread keeps the target that was chosen for it, and the next new
 * chat starts on the Server with the Workspace default again (a device choice never outlives its chat). */
export function adoptNewThreadTarget(sessionId: string | null | undefined) {
  if (!sessionId || !targets.has(NEW_THREAD)) return;
  if (!targets.has(sessionId)) targets.set(sessionId, targets.get(NEW_THREAD) as ExecutionTarget);
  targets.delete(NEW_THREAD);
  notify();
}

export function useExecutionTarget(sessionId: string | null | undefined): ExecutionTarget {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => readExecutionTarget(sessionId),
    () => readExecutionTarget(sessionId),
  );
}

/** The send-body fields of a device target; the Server-only selections are sent empty (the server refuses
 * them with a device target rather than ignoring them). The Server target adds nothing. */
export function executionTargetSendFields(target: ExecutionTarget | undefined) {
  if (!target || target.kind !== "device") return {};
  return {
    execution_target: { kind: "device", device_id: target.deviceId, folder: target.folder, profile: target.profile,
      model: target.model ?? "", permission_mode: target.permissionMode ?? "", effort: target.effort ?? "" },
    workflow_key: "",
    runtime_target_id: "",
    agent_id: "",
  };
}
