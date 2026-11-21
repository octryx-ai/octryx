// Sends the mobile chat's reply: to a taken-over session, to the Server, or as a turn on the job's Mac.

import { buildChatSendBody } from "../chat/chatSendPayload";
import type { DeviceJob } from "../chat/devices/deviceJobTypes";
import { send, takeOver } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import type { ServerOptions } from "./ServerOptionsBar";
import type { useTurnOptions } from "./useTurnOptions";

export function chatPageSubmit({ draft, setDraft, job, onServer, busy, setBusy, setError, localSessionId, forkThreadId,
  refresh, sessionId, projectId, serverOptions, turnOptions }: {
  draft: string;
  setDraft: (draft: string) => void;
  job: DeviceJob | null;
  onServer: boolean;
  busy: boolean;
  setBusy: (busy: boolean) => void;
  setError: (error: string) => void;
  localSessionId?: string;
  forkThreadId?: string;
  refresh: () => Promise<void>;
  sessionId: string;
  projectId: string;
  serverOptions: ServerOptions;
  turnOptions: ReturnType<typeof useTurnOptions>[0];
}) {
  const submit = async () => {
    const prompt = draft.trim();
    if (!prompt || (!job && !onServer) || busy) return;
    setBusy(true);
    setError("");
    try {
      if (localSessionId) {
        await takeOver(localSessionId, prompt, forkThreadId ?? "");
        setDraft("");
        await refresh();
        return;
      }
      await send(
        buildChatSendBody(
          prompt,
          {
            sessionId,
            projectId,
            runtimeTargetId: onServer ? serverOptions.runtimeTargetId : "",
            thinkingLevel: onServer ? serverOptions.thinkingLevel : "light",
            routingOverridesEnabled: false,
            agentId: "",
            workflowKey: "",
            executionTarget:
              onServer || !job
                ? undefined
                : {
                    kind: "device",
                    deviceId: job.deviceId,
                    folder: job.folder,
                    profile: job.profile === "seat" ? "seat" : "governed",
                    model: turnOptions.model,
                    permissionMode: turnOptions.permissionMode,
                    effort: turnOptions.effort,
                  },
          },
          undefined,
          `m-${sessionId}-${Date.now()}`,
        ),
      );
      setDraft("");
      await refresh();
    } catch (reason) {
      setError(
        (reason as MobileError).code?.replace(/_/g, " ") ??
          "The message was not sent.",
      );
    } finally {
      setBusy(false);
    }
  };
  return submit;
}
