import { useCallback, useEffect, useRef, useState } from "react";
import { readJson } from "../../utils/adminPanelHelpers";
import type { AgentExecutionSource, ExecutionLookup } from "./actionGuidedExecution";

const documentUrl = (agentId: string) =>
  `/admin/chat/api/panel/agents/${encodeURIComponent(agentId)}/designer-document`;

type DesignerDocument = {
  execution?: AgentExecutionSource | null;
  revision?: {
    revision_number?: unknown;
    status?: unknown;
    snapshot?: unknown;
  } | null;
};

/**
 * Which content of `agentId` an Action run executes, read from the same endpoint the
 * Agents page uses. Every reply is tagged with the agent it answers and an older reply is
 * dropped, so a slow answer for a previously chosen agent never stands in for the current one.
 */
export function useAgentExecutionSource(agentId: string) {
  const [lookup, setLookup] = useState<ExecutionLookup>({ status: "idle" });
  const [attempt, setAttempt] = useState(0);
  const latest = useRef(0);

  useEffect(() => {
    const request = ++latest.current;
    if (!agentId) {
      setLookup({ status: "idle" });
      return;
    }
    setLookup({ status: "loading", agentId });
    readJson<DesignerDocument>(documentUrl(agentId))
      .then((payload) => {
        if (latest.current !== request) return;
        const revisionNumber = payload?.revision?.revision_number;
        setLookup({
          status: "ready",
          agentId,
          execution: payload?.execution ?? null,
          latestRevision:
            typeof revisionNumber === "number" ? revisionNumber : null,
          latestRevisionStatus:
            typeof payload?.revision?.status === "string"
              ? payload.revision.status
              : null,
          latestSnapshot: payload?.revision?.snapshot,
        });
      })
      .catch((error: unknown) => {
        if (latest.current !== request) return;
        const message = (error as { message?: unknown } | null)?.message;
        setLookup({
          status: "failed",
          agentId,
          error:
            typeof message === "string" && message ? message : "Request failed",
        });
      });
  }, [agentId, attempt]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { lookup, retry };
}
