// The Flow Builder tab's actions: run trace, test cases, flow loading and validation, publishing, runs and the
// editor's handlers, wired to each other in the order they depend on.
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { flowBuilderEditorHandlers } from "./flowBuilderEditorHandlers";
import { flowBuilderFlowActions } from "./flowBuilderFlowActions";
import { flowBuilderPublishActions } from "./flowBuilderPublishActions";
import { flowBuilderRunActions } from "./flowBuilderRunActions";
import { flowRunTraceActions } from "./flowRunTraceActions";
import { flowTestCaseActions } from "./flowTestCaseActions";
import type { FlowBuilderState } from "./useFlowBuilderState";

export type FlowBuilderTabActions = ReturnType<typeof flowBuilderTabActions>;

export function flowBuilderTabActions({ state, readJson, onExit }: {
  state: FlowBuilderState;
  readJson: ReadJsonFn;
  onExit: () => void;
}) {
  const { resolvePausedRun, cancelPausedRun, recoverInterruptedRun, loadRunQuality, evaluateCurrentRun } = flowRunTraceActions({
    readJson, ...state,
  });

  const { loadTestCases, createTestCase, runTestCase, batchRunTestCases } = flowTestCaseActions({
    readJson, ...state, loadRunQuality,
  });

  const { loadFlowCapabilities, loadFlowDetail, validateCurrentFlow, createFlowDraft } = flowBuilderFlowActions({ ...state, readJson, loadTestCases });
  const { publishSelectedFlow, unpublishSelectedCapability, rejectSelectedFlow } = flowBuilderPublishActions({ ...state, readJson, loadFlowCapabilities });
  const { runSelectedFlow, refreshRunTrace, runSelectedNodePartial } = flowBuilderRunActions({ ...state, readJson, validateCurrentFlow, loadRunQuality });
  const { openCreatedDraft, returnToLibrary, handleExpertDefinitionChange, handleNodeUpdate, focusValidationIssue, handleNodeRestore } =
    flowBuilderEditorHandlers({ ...state, onExit, loadFlowDetail });

  return {
    resolvePausedRun, cancelPausedRun, recoverInterruptedRun, loadRunQuality, evaluateCurrentRun,
    loadTestCases, createTestCase, runTestCase, batchRunTestCases,
    loadFlowCapabilities, loadFlowDetail, validateCurrentFlow, createFlowDraft,
    publishSelectedFlow, unpublishSelectedCapability, rejectSelectedFlow,
    runSelectedFlow, refreshRunTrace, runSelectedNodePartial,
    openCreatedDraft, returnToLibrary, handleExpertDefinitionChange, handleNodeUpdate, focusValidationIssue, handleNodeRestore,
  };
}
