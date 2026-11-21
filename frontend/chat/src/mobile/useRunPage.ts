// Loads one workflow run for the phone and polls it while it is not finished.
import { useCallback, useEffect, useState } from "react";
import type { WorkflowRun } from "../chat/workflowRun/workflowRunTypes";
import { loadRun } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { isFinished } from "./mobileRuns";
import { useRefreshEvent } from "./pullToRefresh";

const POLL_MS = 5000;

export type RunPayload = WorkflowRun & { project_id?: string; sessions?: unknown; responsible?: unknown; created_at?: string };

export function useRunPage(runId: string) {
  const [run, setRun] = useState<RunPayload | null>(null);
  const [error, setError] = useState("");
  const [sent, setSent] = useState("");

  const refresh = useCallback(async () => {
    try {
      setRun((await loadRun(runId)).run as RunPayload);
      setError("");
    } catch (reason) {
      setError((reason as MobileError).status === 404 ? "This run is not there or not yours to see." : "The run could not be loaded.");
    }
  }, [runId]);
  useRefreshEvent(refresh);
  const finished = run ? isFinished(run.status) : false;
  useEffect(() => {
    void refresh();
    if (finished) return;
    const timer = window.setInterval(() => !document.hidden && void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, finished]);

  const acted = (next: WorkflowRun) => {
    setRun(next as RunPayload);
    setSent("Sent. The run goes on with your answer.");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  return { run, error, sent, finished, acted };
}
