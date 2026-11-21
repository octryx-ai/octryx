// Flow Builder: editor handlers for the canvas, the selected step, version restore and leaving the editor.
import { parseJsonObject } from "./flowBuilderDefinition";
import { EMPTY_DEFINITION, EMPTY_REPORT, prettyJson } from "./flowBuilderDefaults";
import type { FlowDefinitionJson, FlowDefinitionNode, FlowDefinitionRow, FlowDefinitionVersion } from "./flowBuilderTypes";
import { validationIssueNodeId } from "./flowValidationFeedback";
import type { FlowBuilderState } from "./useFlowBuilderState";

type FlowBuilderEditorHandlersInput = FlowBuilderState & {
  onExit: () => void;
  loadFlowDetail: (flowId: string) => Promise<boolean>;
};

export function flowBuilderEditorHandlers({
  onExit, loadFlowDetail, setCreateDrawerOpen, setProjectId, setFlowDetailsOpen, setNewDraftGuide, setExpertJson,
  selectedNodeId, expertJson, activeDefinition, setSelectedNodeId, setAuthoringVersionId, setValidationReport,
  setVersionHistoryOpen, setRunTrace, setSelectedTraceNodeRunId,
}: FlowBuilderEditorHandlersInput) {
  async function openCreatedDraft(flow: FlowDefinitionRow) {
    setCreateDrawerOpen(false);
    setProjectId(flow.project_id || "");
    if (!await loadFlowDetail(flow.id)) return;
    setFlowDetailsOpen(true);
    setNewDraftGuide(true);
  }

  // The Workflows page asks before unsaved edits are dropped (its ConfirmDialog, fed by onDirtyChange) and then
  // unmounts this editor, so leaving is a hand-back only.
  function returnToLibrary() {
    onExit();
  }

  function handleExpertDefinitionChange(def: FlowDefinitionJson) {
    setExpertJson(prettyJson(def));
  }

  function handleNodeUpdate(patch: Partial<FlowDefinitionNode>) {
    if (!selectedNodeId) return;
    const def = parseJsonObject<FlowDefinitionJson>(expertJson);
    const updated = {
      ...def,
      nodes: def.nodes.map((n) =>
        n.id === selectedNodeId ? { ...n, ...patch } : n,
      ),
      edges: def.edges,
    };
    setExpertJson(prettyJson(updated));
  }

  function focusValidationIssue(issue: { message: string }) {
    const nodeId = validationIssueNodeId(issue.message, activeDefinition.nodes.map((node) => node.id));
    if (nodeId) setSelectedNodeId(nodeId);
  }

  function handleNodeRestore(version: FlowDefinitionVersion) {
    setAuthoringVersionId(version.id);
    setExpertJson(prettyJson(version.definition || EMPTY_DEFINITION));
    setValidationReport(version.validation_report || EMPTY_REPORT);
    setVersionHistoryOpen(false);
    setRunTrace(null);
    setSelectedTraceNodeRunId(null);
  }

  return { openCreatedDraft, returnToLibrary, handleExpertDefinitionChange, handleNodeUpdate, focusValidationIssue, handleNodeRestore };
}
