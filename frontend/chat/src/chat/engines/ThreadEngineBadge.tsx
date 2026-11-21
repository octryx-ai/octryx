import type { ChatMessage, SelectedSession } from "../../chatThreadTypes";
import { isDeviceThread } from "../transcripts/useThreadTranscript";
import { useThreadDeviceJobs } from "../transcripts/useTranscriptItems";
import { EngineBadge } from "./EngineBadge";

/** The chat header's engine badge: the coding engine of the thread's newest device job (a device chat or a device
 * workflow run); nothing on a thread without a device job. */
export function ThreadEngineBadge({ selectedSession, runsOnDevice, messages }: {
  selectedSession: SelectedSession | null;
  runsOnDevice: boolean;
  messages: ChatMessage[];
}) {
  const jobs = useThreadDeviceJobs(selectedSession?.id, isDeviceThread(selectedSession, runsOnDevice, messages));
  const latest = jobs.length ? jobs[jobs.length - 1] : null;
  return latest ? <EngineBadge engine={latest.engine} /> : null;
}
