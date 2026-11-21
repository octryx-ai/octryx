import type { ChatMessage, SelectedSession } from "../../chatThreadTypes";
import { useTranscriptViewer } from "./TranscriptButton";
import { useThreadDeviceJobIds, useTranscriptItems } from "./useTranscriptItems";

/**
 * The chat header's transcript entry: an octryx-claude session's own transcript, or those of the
 * thread's newest device jobs. `available` is false until one is stored and readable.
 */
/** Whether a thread runs (or ran) on a device: a device chat or a device workflow run, not an octryx session. */
export function isDeviceThread(selectedSession: SelectedSession | null, runsOnDevice: boolean, messages: ChatMessage[]): boolean {
  const gatewaySession = selectedSession?.agentType === "external_agent";
  return !gatewaySession && (runsOnDevice || messages.some((message) => message.origin === "device"));
}

export function useThreadTranscript(selectedSession: SelectedSession | null, runsOnDevice: boolean, messages: ChatMessage[]) {
  const gatewaySession = selectedSession?.agentType === "external_agent";
  const deviceThread = isDeviceThread(selectedSession, runsOnDevice, messages);
  const deviceJobIds = useThreadDeviceJobIds(selectedSession?.id, deviceThread);
  return useTranscriptViewer(useTranscriptItems(
    selectedSession?.projectId,
    gatewaySession && selectedSession ? [{ sessionId: selectedSession.id }] : deviceJobIds.map((id) => ({ deviceJobId: id })),
  ));
}
