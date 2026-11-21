import { useCallback, useEffect, useState } from "react";
import { readJson } from "../../utils/adminPanelHelpers";
import type { AgentExecutionSource, AgentRevision } from "./agentWorkspaceModel";

const documentUrl = (agentId: string) => `/admin/chat/api/panel/agents/${encodeURIComponent(agentId)}/designer-document`;

// Revision state of one agent from the governed revision boundary: panel edits
// append draft revisions; publishing stays an explicit action on the shown
// revision (same endpoint and compare-and-publish rule).
export function useAgentRevision(agentId: string, changeKey: string) {
  const [revision, setRevision] = useState<AgentRevision | null>(null);
  const [execution, setExecution] = useState<AgentExecutionSource | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  const load = useCallback(async () => {
    setState("loading");
    try {
      const payload = await readJson<{ revision?: AgentRevision | null; execution?: AgentExecutionSource }>(
        documentUrl(agentId),
      );
      setRevision(payload?.revision ?? null);
      setExecution(payload?.execution ?? null);
      setState("ready");
    } catch {
      setState("error");
    }
  }, [agentId]);

  useEffect(() => { void load(); }, [load, changeKey]);

  const publish = useCallback(async () => {
    if (!revision || revision.status !== "draft") return;
    setPublishing(true); setMessage(null);
    try {
      const published = await readJson<AgentRevision>(`${documentUrl(agentId)}/publish`, {
        method: "POST",
        body: JSON.stringify({ revision_id: revision.id }),
      });
      setRevision(published ?? revision);
      void load();
      setMessage(`Published revision ${published?.revision_number ?? revision.revision_number}.`);
    } catch (error) {
      setMessage(error instanceof Error ? `Not published: ${error.message}` : "Not published.");
      void load();
    } finally {
      setPublishing(false);
    }
  }, [agentId, load, revision]);

  return { revision, execution, state, message, publishing, publish, reload: load };
}
