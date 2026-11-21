import { useEffect, useState } from "react";
import { readJson } from "../../utils/adminPanelHelpers";
import { agentReferencesUrl, type AgentReferencesPayload } from "./agentReferencesModel";

export type AgentReferencesState = "loading" | "ready" | "error";

// Reads which workflows the caller can see use this agent.
export function useAgentReferences(agentId: string) {
  const [payload, setPayload] = useState<AgentReferencesPayload | null>(null);
  const [state, setState] = useState<AgentReferencesState>("loading");

  useEffect(() => {
    let cancelled = false;
    setState("loading");
    setPayload(null);
    readJson<AgentReferencesPayload>(agentReferencesUrl(agentId))
      .then((result) => {
        if (cancelled) return;
        setPayload(result);
        setState("ready");
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  return { payload, state };
}
