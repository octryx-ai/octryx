// What blocks a new chat on the phone, and starting it with its first message.
import { buildChatSendBody } from "../chat/chatSendPayload";
import type { MyDevice } from "../chat/devices/devicesModel";
import type { DeviceRunsPolicy } from "../chat/devices/deviceRunsPolicyModel";
import { send } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import type { Billing } from "./mobileDeviceChats";
import type { NewChatSheetState } from "./useNewChatSheet";

export function newChatBlocked(
  onServer: boolean,
  device: MyDevice | null,
  policy: DeviceRunsPolicy | null,
  options: Billing[],
): string {
  return onServer
    ? ""
    : !device
      ? "Connect a Mac first: octryx-claude device enable."
      : !device.connected
        ? `${device.name} is offline.`
        : policy && !policy.enabled
          ? "This Workspace does not run chats on Macs."
          : policy && !options.length
            ? "Neither API nor Seat is available for this Mac in this Workspace."
            : "";
}

function newChatBody(state: NewChatSheetState, onServer: boolean, device: MyDevice | null) {
  const { projectId, serverOptions, folder, billing, turnOptions } = state;
  return buildChatSendBody(
    state.prompt.trim(),
    {
      sessionId: "",
      projectId,
      runtimeTargetId: onServer ? serverOptions.runtimeTargetId : "",
      thinkingLevel: onServer ? serverOptions.thinkingLevel : "light",
      routingOverridesEnabled: false,
      agentId: "",
      workflowKey: "",
      executionTarget:
        onServer || !device
          ? undefined
          : {
              kind: "device",
              deviceId: device.id,
              folder,
              profile: billing,
              model: turnOptions.model,
              permissionMode: turnOptions.permissionMode,
              effort: turnOptions.effort,
            },
    },
    undefined,
    `m-new-${Date.now()}`,
  );
}

export async function startNewChat(
  state: NewChatSheetState,
  target: { onServer: boolean; device: MyDevice | null; blocked: string },
  onStarted: (sessionId: string, projectId: string, title: string, onServer: boolean) => void,
) {
  const { onServer, device, blocked } = target;
  const { prompt, busy, setBusy, setError, projectId } = state;
  if ((!device && !onServer) || !prompt.trim() || busy || blocked) return;
  setBusy(true);
  setError("");
  try {
    const result = await send(newChatBody(state, onServer, device));
    const id = result.selectedSession?.id;
    if (id) onStarted(id, projectId, prompt.trim().slice(0, 60), onServer);
    else setError("The chat did not start.");
  } catch (reason) {
    setError(
      (reason as MobileError).code?.replace(/_/g, " ") ??
        "The chat did not start.",
    );
  } finally {
    setBusy(false);
  }
}
