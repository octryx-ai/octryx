// Flow Builder: actions on the loaded run (resume, cancel or recover it, load and evaluate its quality summary).
import type { Dispatch, SetStateAction } from "react";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { parseJsonObject } from "./flowBuilderDefinition";
import type { FlowQualityEvaluationPayload, FlowQualitySummary, FlowRunTracePayload } from "./flowRunTypes";

type FlowRunTraceActionsInput = {
  readJson: ReadJsonFn;
  runTrace: FlowRunTracePayload | null;
  traceInputJson: string;
  setError: Dispatch<SetStateAction<string | null>>;
  setRunBusy: Dispatch<SetStateAction<boolean>>;
  setRunTrace: Dispatch<SetStateAction<FlowRunTracePayload | null>>;
  setSelectedTraceNodeRunId: Dispatch<SetStateAction<string | null>>;
  setOperationsOpen: Dispatch<SetStateAction<boolean>>;
  setQualitySummary: Dispatch<SetStateAction<FlowQualitySummary | null>>;
  setQualityBusy: Dispatch<SetStateAction<boolean>>;
};
type LoadRunQuality = (runId?: string) => Promise<void>;

export function flowRunTraceActions(input: FlowRunTraceActionsInput) {
  const { loadRunQuality, evaluateCurrentRun } = qualityActions(input);
  return { ...runControlActions(input, loadRunQuality), loadRunQuality, evaluateCurrentRun };
}

// Posts one run action and shows the trace it answers with, then that run's quality summary.
async function postRunAction(
  input: FlowRunTraceActionsInput,
  loadRunQuality: LoadRunQuality,
  url: string,
  body: Record<string, unknown>,
  failure: string,
) {
  const { readJson, setError, setRunBusy, setRunTrace, setSelectedTraceNodeRunId, setOperationsOpen } = input;
  setRunBusy(true);
  setError(null);
  try {
    const trace = await readJson<FlowRunTracePayload>(url, { method: "POST", body: JSON.stringify(body) });
    setRunTrace(trace);
    setSelectedTraceNodeRunId(trace.node_runs?.[0]?.id ?? null);
    setOperationsOpen(true);
    await loadRunQuality(trace.run.id);
  } catch (err) {
    setError(err instanceof Error ? err.message : failure);
  } finally {
    setRunBusy(false);
  }
}

function runControlActions(input: FlowRunTraceActionsInput, loadRunQuality: LoadRunQuality) {
  const { runTrace, traceInputJson, setError } = input;
  async function resolvePausedRun(decision: "approve" | "reject", approvalId: string | null) {
    const runId = runTrace?.run?.id;
    if (!runId || !approvalId) {
      setError("Paused run approval is missing.");
      return;
    }
    let humanInput: Record<string, unknown> = {};
    if (decision === "approve") {
      try {
        humanInput = parseJsonObject<Record<string, unknown>>(traceInputJson);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Trace input must be valid JSON.");
        return;
      }
    }
    const reason = decision === "approve" ? "Approved from Flow Builder trace" : "Rejected from Flow Builder trace";
    await postRunAction(input, loadRunQuality, `/api/v1/flows/runs/${runId}/resume`,
      { decision, approval_id: approvalId, human_input: humanInput, reason }, "Flow resume failed");
  }

  async function cancelPausedRun() {
    const runId = runTrace?.run?.id;
    if (!runId) {
      setError("No paused run is loaded.");
      return;
    }
    await postRunAction(input, loadRunQuality, `/api/v1/flows/runs/${runId}/cancel`,
      { reason: "Cancelled from Flow Builder trace" }, "Flow cancel failed");
  }

  async function recoverInterruptedRun() {
    const runId = runTrace?.run?.id;
    if (!runId) {
      setError("No run is loaded.");
      return;
    }
    await postRunAction(input, loadRunQuality, `/api/v1/flows/runs/${runId}/resume-interrupted`,
      { reason: "Recovered from Flow Builder trace" }, "Flow recovery failed");
  }
  return { resolvePausedRun, cancelPausedRun, recoverInterruptedRun };
}

function qualityActions({ readJson, runTrace, setError, setQualitySummary, setQualityBusy }: FlowRunTraceActionsInput) {
  async function loadRunQuality(runId = runTrace?.run.id) {
    if (!runId) {
      setQualitySummary(null);
      return;
    }
    setQualityBusy(true);
    setError(null);
    try {
      const summary = await readJson<FlowQualitySummary>(`/api/v1/flows/runs/${runId}/quality`);
      setQualitySummary(summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Quality summary failed");
    } finally {
      setQualityBusy(false);
    }
  }

  async function evaluateCurrentRun() {
    const runId = runTrace?.run.id;
    if (!runId) {
      setError("Run a flow before evaluating quality.");
      return;
    }
    setQualityBusy(true);
    setError(null);
    try {
      const result = await readJson<FlowQualityEvaluationPayload>(
        `/api/v1/flows/runs/${runId}/evaluate`,
        { method: "POST", body: JSON.stringify({}) },
      );
      setQualitySummary(result.quality_summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Flow evaluation failed");
    } finally {
      setQualityBusy(false);
    }
  }
  return { loadRunQuality, evaluateCurrentRun };
}
