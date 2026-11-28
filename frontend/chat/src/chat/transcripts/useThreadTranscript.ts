import type { ChatMessage, SelectedSession } from "../../chatThreadTypes";
import { useTranscriptViewer } from "./TranscriptButton";
import { useThreadDeviceJobIds, useTranscriptItems } from "./useTranscriptItems";

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
