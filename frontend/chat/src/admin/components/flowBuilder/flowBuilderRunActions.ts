// Flow Builder: run the saved revision (whole flow or from the selected step) and refresh the loaded trace.
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import type { FlowRunTracePayload } from "./flowRunTypes";
import { flowRunRequest } from "./flowRunRequest";
import { needsValidationRefresh } from "./flowFailureMessages";
import type { FlowBuilderState } from "./useFlowBuilderState";

type FlowBuilderRunActionsInput = FlowBuilderState & {
  readJson: ReadJsonFn;
  validateCurrentFlow: (options?: { reveal?: boolean }) => Promise<void>;
  loadRunQuality: (runId?: string) => Promise<void>;
};

export function flowBuilderRunActions({
  readJson, validateCurrentFlow, loadRunQuality, nextAction, authoring, runWorkspaceId, traceInputJson,
  setError, setRunBusy, setRunTrace, setSelectedTraceNodeRunId, setOperationsOpen, runTrace, selectedNodeId, setTestBusy,
}: FlowBuilderRunActionsInput) {
  async function runSelectedFlow() {
    // Exactly the saved revision shown (authoring.version), only when the next action is "run".
    const request = flowRunRequest(nextAction, authoring.version?.id, { projectId: runWorkspaceId, inputJson: traceInputJson });
    if (!request.ok) { setError(request.error); return; }
    setRunBusy(true);
    setError(null);
    try {
      const trace = await readJson<FlowRunTracePayload>(request.path, { method: "POST", body: request.body });
      setRunTrace(trace);
      setSelectedTraceNodeRunId(trace.node_runs?.[0]?.id ?? null);
      setOperationsOpen(true);
      await loadRunQuality(trace.run.id);
      if (needsValidationRefresh(trace)) await validateCurrentFlow(); // stale "Ready to run" → current blockers
    } catch (err) {
      setError(err instanceof Error ? err.message : "Flow run failed");
    } finally {
      setRunBusy(false);
    }
  }

  async function refreshRunTrace() {
    const runId = runTrace?.run?.id;
    if (!runId) return;
    setRunBusy(true);
    setError(null);
    try {
      const trace = await readJson<FlowRunTracePayload>(
        `/api/v1/flows/runs/${runId}/trace`,
      );
      setRunTrace(trace);
      setSelectedTraceNodeRunId((current) => current ?? trace.node_runs?.[0]?.id ?? null);
      setOperationsOpen(true);
      await loadRunQuality(trace.run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Trace refresh failed");
    } finally {
      setRunBusy(false);
    }
  }

  async function runSelectedNodePartial() {
    const request = flowRunRequest(nextAction, authoring.version?.id, {
      projectId: runWorkspaceId, inputJson: traceInputJson, nodeId: selectedNodeId,
    });
    if (!request.ok) { setError(request.error); return; }
    setTestBusy(true);
    setError(null);
    try {
      const trace = await readJson<FlowRunTracePayload>(request.path, { method: "POST", body: request.body });
      setRunTrace(trace);
      setSelectedTraceNodeRunId(trace.node_runs?.[0]?.id ?? null);
      setOperationsOpen(true);
      await loadRunQuality(trace.run.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Partial run failed");
    } finally {
      setTestBusy(false);
    }
  }

  return { runSelectedFlow, refreshRunTrace, runSelectedNodePartial };
}
