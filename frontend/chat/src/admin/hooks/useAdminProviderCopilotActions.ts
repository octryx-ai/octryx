import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import type { AdminProvider } from "../types/adminPanelTypes.usersProviders";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type CopilotFlow = {
  providerId: string;
  flowId: string;
  userCode: string;
  verificationUri: string;
  interval: number;
  status: "pending" | "waiting" | "connected" | "failed";
  error?: string;
  login?: string;
};

type CreateCopilotActionsArgs = {
  readJson: ReadJsonFn;
  setCopilotFlow: Dispatch<SetStateAction<CopilotFlow | null>>;
  setProviders: Dispatch<SetStateAction<AdminProvider[]>>;
  copilotPollRef: MutableRefObject<ReturnType<typeof setInterval> | null>;
};

type CopilotPollResult = {
  status: string;
  login?: string;
  error?: string;
  interval?: number;
};

function stopCopilotPoll(copilotPollRef: CreateCopilotActionsArgs["copilotPollRef"]) {
  if (copilotPollRef.current) {
    clearInterval(copilotPollRef.current);
  }
  copilotPollRef.current = null;
}

function applyCopilotPollResult(
  { setCopilotFlow, setProviders, copilotPollRef }: CreateCopilotActionsArgs,
  providerId: string,
  result: CopilotPollResult,
  poll: () => Promise<void>,
) {
  if (result.status === "connected") {
    stopCopilotPoll(copilotPollRef);
    setCopilotFlow((prev) =>
      prev
        ? { ...prev, status: "connected", login: result.login }
        : prev,
    );
    setProviders((prev) =>
      prev.map((provider) =>
        provider.id === providerId
          ? {
              ...provider,
              has_api_key: true,
              api_key_masked: "OAuth: " + (result.login || "GitHub"),
            }
          : provider,
      ),
    );
  } else if (result.status === "failed") {
    stopCopilotPoll(copilotPollRef);
    setCopilotFlow((prev) =>
      prev ? { ...prev, status: "failed", error: result.error } : prev,
    );
  } else if (result.status === "waiting" && result.interval) {
    if (copilotPollRef.current) {
      clearInterval(copilotPollRef.current);
    }
    copilotPollRef.current = setInterval(
      poll,
      (result.interval || 10) * 1000,
    );
    setCopilotFlow((prev) =>
      prev
        ? {
            ...prev,
            status: "waiting",
            interval: result.interval || prev.interval,
          }
        : prev,
    );
  }
}

// One poll of the GitHub device flow; a slower interval from the server restarts the poll with it.
function copilotFlowPoller(args: CreateCopilotActionsArgs, providerId: string, flowId: string) {
  const { readJson, setCopilotFlow, copilotPollRef } = args;
  const pollCopilotFlow = async () => {
    try {
      const result = await readJson<CopilotPollResult>(
        `/admin/chat/api/panel/providers/${providerId}/copilot/device/poll`,
        {
          method: "POST",
          body: JSON.stringify({ flow_id: flowId }),
        },
      );
      applyCopilotPollResult(args, providerId, result, pollCopilotFlow);
    } catch (err) {
      stopCopilotPoll(copilotPollRef);
      setCopilotFlow((prev) =>
        prev
          ? {
              ...prev,
              status: "failed",
              error:
                err instanceof Error
                  ? err.message
                  : "Failed to poll GitHub authorization",
            }
          : prev,
      );
    }
  };
  return pollCopilotFlow;
}

export function createCopilotActions(args: CreateCopilotActionsArgs) {
  const { readJson, setCopilotFlow, copilotPollRef } = args;
  const handleCopilotConnect = async (providerId: string) => {
    if (copilotPollRef.current) {
      clearInterval(copilotPollRef.current);
    }
    try {
      const data = await readJson<{
        flow_id: string;
        user_code: string;
        verification_uri: string;
        interval: number;
        client_id?: string;
      }>(`/admin/chat/api/panel/providers/${providerId}/copilot/device/start`, {
        method: "POST",
      });
      const flow = {
        providerId,
        flowId: data.flow_id,
        userCode: data.user_code,
        verificationUri: data.verification_uri,
        interval: data.interval,
        status: "pending" as const,
      };
      setCopilotFlow(flow);
      copilotPollRef.current = setInterval(
        copilotFlowPoller(args, providerId, data.flow_id),
        flow.interval * 1000,
      );
    } catch (err) {
      window.alert(
        err instanceof Error ? err.message : "Failed to start Copilot login",
      );
    }
  };

  const handleCopilotDisconnect = () => {
    stopCopilotPoll(copilotPollRef);
    setCopilotFlow(null);
  };

  return { handleCopilotConnect, handleCopilotDisconnect };
}
