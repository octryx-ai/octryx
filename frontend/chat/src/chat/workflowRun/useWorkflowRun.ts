import { useCallback, useEffect, useRef, useState } from "react";

import { readJson } from "../chatApiClient";
import { runActionRequest, runBySessionPath } from "./workflowRunRequests";
import { type RunAction, type RunActionValue, type WorkflowRun } from "./workflowRunTypes";

// The run the selected chat session follows. Reloaded whenever `refreshKey` changes (a new message in the
// timeline), so the banner shows the run's state after every turn.
export function useWorkflowRun(
  sessionId: string | null | undefined,
  refreshKey: unknown,
) {
  // The run is kept with the session it was loaded for, so a switch to another chat never shows the previous run.
  const [loaded, setLoaded] = useState<{ sessionId: string | null; run: WorkflowRun | null }>({ sessionId: null, run: null });
  const run = loaded.sessionId === (sessionId ?? null) ? loaded.run : null;
  const currentSession = useRef(sessionId ?? null);
  useEffect(() => {
    // Before the load effect below: an answer for a chat that is no longer open is dropped.
    currentSession.current = sessionId ?? null;
  }, [sessionId]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!sessionId) {
      setLoaded({ sessionId: null, run: null });
      return;
    }
    try {
      const payload = await readJson<{ run: WorkflowRun | null }>(
        runBySessionPath(sessionId),
      );
      if (currentSession.current === sessionId) setLoaded({ sessionId, run: payload.run });
    } catch {
      if (currentSession.current === sessionId) setLoaded({ sessionId, run: null });
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const act = useCallback(
    async (
      action: RunAction,
      input?: RunActionValue,
    ): Promise<{ session_id?: string } | null> => {
      if (!run) return null;
      const request = runActionRequest(run, action, input);
      setBusy(true);
      setProblem(null);
      try {
        const payload = await readJson<{
          run: WorkflowRun;
          session_id?: string;
        }>(request.path, {
          method: "POST",
          body: JSON.stringify(request.body),
        });
        setLoaded({ sessionId: sessionId ?? null, run: payload.run });
        return payload;
      } catch (error) {
        setProblem(
          error instanceof Error ? error.message : "The action failed.",
        );
        // A refusal can mean the run changed meanwhile (a refreshed payload, another decision): show it.
        void load();
        return null;
      } finally {
        setBusy(false);
      }
    },
    [run, load, sessionId],
  );

  return { run, busy, problem, act, reload: load };
}
