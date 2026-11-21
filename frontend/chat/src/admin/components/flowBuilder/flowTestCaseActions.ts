// Flow Builder: the saved test cases of a flow (load, create, run one, run all).
import type { Dispatch, SetStateAction } from "react";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import type { flowAuthoringState } from "./flowAuthoringState";
import { parseJsonObject } from "./flowBuilderDefinition";
import type { FlowDefinitionRow } from "./flowBuilderTypes";
import { RUN_WORKSPACE_REQUIRED } from "./flowRunRequest";
import type { FlowRunTracePayload, FlowTestCase, FlowTestCaseBatchPayload, FlowTestCaseListPayload, FlowTestCaseRunPayload } from "./flowRunTypes";

type FlowTestCaseActionsInput = {
  readJson: ReadJsonFn;
  selectedFlow: FlowDefinitionRow | null;
  authoring: Pick<ReturnType<typeof flowAuthoringState>, "testsAvailable">;
  runWorkspaceId: string | null;
  traceInputJson: string;
  setError: Dispatch<SetStateAction<string | null>>;
  setTestBusy: Dispatch<SetStateAction<boolean>>;
  setTestCases: Dispatch<SetStateAction<FlowTestCase[]>>;
  setRunTrace: Dispatch<SetStateAction<FlowRunTracePayload | null>>;
  setSelectedTraceNodeRunId: Dispatch<SetStateAction<string | null>>;
  setOperationsOpen: Dispatch<SetStateAction<boolean>>;
  loadRunQuality: (runId?: string) => Promise<void>;
};

async function loadFlowTestCases(
  { readJson, setTestCases }: FlowTestCaseActionsInput,
  flowId: string | undefined,
) {
  if (!flowId) {
    setTestCases([]);
    return;
  }
  try {
    const payload = await readJson<FlowTestCaseListPayload>(
      `/api/v1/flows/${flowId}/test-cases`,
    );
    setTestCases(Array.isArray(payload.items) ? payload.items : []);
  } catch (err) {
    console.error("Failed to load flow test cases", err);
    setTestCases([]);
  }
}

async function createFlowTestCase(
  { readJson, selectedFlow, authoring, runWorkspaceId, traceInputJson, setError, setTestBusy }: FlowTestCaseActionsInput,
  loadTestCases: (flowId?: string) => Promise<void>,
  testName: string,
  expectedOutputJson: string,
) {
  if (!authoring.testsAvailable) { setError("Test cases require the saved default revision. Use Run to test this draft."); return; }
  if (!selectedFlow?.id) {
    setError("Select or create a flow before saving a test case.");
    return;
  }
  if (!runWorkspaceId) { setError(RUN_WORKSPACE_REQUIRED); return; } // its runs start in that Workspace
  let input: Record<string, unknown>;
  let expectedOutput: Record<string, unknown>;
  try {
    input = parseJsonObject<Record<string, unknown>>(traceInputJson);
    expectedOutput = parseJsonObject<Record<string, unknown>>(expectedOutputJson || "{}");
  } catch (err) {
    setError(err instanceof Error ? err.message : "Test input and expected output must be valid JSON objects.");
    return;
  }
  setTestBusy(true);
  setError(null);
  try {
    await readJson<FlowTestCase>(`/api/v1/flows/${selectedFlow.id}/test-cases`, {
      method: "POST",
      body: JSON.stringify({
        name: testName,
        project_id: runWorkspaceId,
        input,
        expected_output: expectedOutput,
      }),
    });
    await loadTestCases(selectedFlow.id);
  } catch (err) {
    setError(err instanceof Error ? err.message : "Failed to save test case");
  } finally {
    setTestBusy(false);
  }
}

async function runFlowTestCase(
  {
    readJson, selectedFlow, authoring, setError, setTestBusy, setRunTrace, setSelectedTraceNodeRunId, setOperationsOpen,
    loadRunQuality,
  }: FlowTestCaseActionsInput,
  loadTestCases: (flowId?: string) => Promise<void>,
  testCaseId: string,
) {
  if (!authoring.testsAvailable) { setError("Test cases require the saved default revision. Use Run to test this draft."); return; }
  if (!selectedFlow?.id) return;
  setTestBusy(true);
  setError(null);
  try {
    const result = await readJson<FlowTestCaseRunPayload>(
      `/api/v1/flows/${selectedFlow.id}/test-cases/${testCaseId}/run`,
      { method: "POST" },
    );
    if (result.trace) {
      setRunTrace(result.trace);
      setSelectedTraceNodeRunId(result.trace.node_runs?.[0]?.id ?? null);
      setOperationsOpen(true);
      await loadRunQuality(result.trace.run.id);
    }
    await loadTestCases(selectedFlow.id);
  } catch (err) {
    setError(err instanceof Error ? err.message : "Test case run failed");
  } finally {
    setTestBusy(false);
  }
}

async function batchRunFlowTestCases(
  { readJson, selectedFlow, authoring, setError, setTestBusy }: FlowTestCaseActionsInput,
  loadTestCases: (flowId?: string) => Promise<void>,
) {
  if (!authoring.testsAvailable) { setError("Test cases require the saved default revision. Use Run to test this draft."); return; }
  if (!selectedFlow?.id) return;
  setTestBusy(true);
  setError(null);
  try {
    await readJson<FlowTestCaseBatchPayload>(
      `/api/v1/flows/${selectedFlow.id}/test-cases/batch-run`,
      { method: "POST", body: JSON.stringify({}) },
    );
    await loadTestCases(selectedFlow.id);
  } catch (err) {
    setError(err instanceof Error ? err.message : "Batch run failed");
  } finally {
    setTestBusy(false);
  }
}

export function flowTestCaseActions(input: FlowTestCaseActionsInput) {
  const { selectedFlow } = input;
  async function loadTestCases(flowId = selectedFlow?.id) {
    return loadFlowTestCases(input, flowId);
  }

  async function createTestCase(testName: string, expectedOutputJson: string) {
    return createFlowTestCase(input, loadTestCases, testName, expectedOutputJson);
  }

  async function runTestCase(testCaseId: string) {
    return runFlowTestCase(input, loadTestCases, testCaseId);
  }

  async function batchRunTestCases() {
    return batchRunFlowTestCases(input, loadTestCases);
  }

  return { loadTestCases, createTestCase, runTestCase, batchRunTestCases };
}
