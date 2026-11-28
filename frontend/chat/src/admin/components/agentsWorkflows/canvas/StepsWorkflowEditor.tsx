// One phase of a workflow that runs in phases, opened in the Canvas: its steps and checks as a diagram, edited
// in place. Saving creates a new draft version of the workflow; the workflow publishes, not the phase. Built for the
// flow builder's editor layout.
// "+ Step" / "+ Check" and a click on a node open the design system's side panel: a new step or
// check is a local draft there and joins the workflow draft only with "Add step" / "Add check"; an existing one is
// edited in place, with Move earlier / later in the footer and Remove in the panel's ⋯ menu.
import { useCallback, useEffect } from "react";
import { ReactFlowProvider } from "@xyflow/react";

import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import "../../flowBuilder/flowBuilder.css";
import { StepsCanvas } from "./StepsCanvas";
import { StepsEditorHeader } from "./StepsEditorHeader";
import { StepsAddPanel, StepsEditorNotices, StepsNodePanel } from "./StepsWorkflowPanels";
import { insertNode, newCheck, newStep, readStepsGraphView, type StepsGraphNode, type StepsGraphView } from "./stepsGraphModel";
import { applyStepsPreview, message, saveStepsDraft, useStepsWorkflowState, type StepsWorkflowState } from "./stepsWorkflowState";
import "./workflowCanvas.css";

const PREVIEW_DELAY_MS = 300;
const TOOL_CATALOG_PATH = "/admin/chat/api/panel/tool-catalog";

type StepsWorkflowEditorProps = {
  // The phase's own graph address (phasedWorkflowModel.phaseGraphPath).
  graphPath: string;
  readJson: ReadJsonFn;
  // Reports unsaved edits to the page, which confirms before switching workflows or views.
  onDirtyChange?: (dirty: boolean) => void;
  // "← Phases": back to the workflow's chart.
  onBack: () => void;
};

// Loads the workflow and the tool names, and previews every edit on the server.
function useStepsWorkflowLoading(state: StepsWorkflowState, readJson: ReadJsonFn, graphPath: string) {
  const { setView, setNodes, setReport, setDirty, setProblem, setToolNames, previewRequest, nodes, dirty } = state;
  const open = useCallback(async () => {
    previewRequest.current += 1; // a preview still in flight never lands on the reloaded definition
    try {
      const next = readStepsGraphView(await readJson<unknown>(graphPath));
      setView(next);
      setNodes(next.graph.nodes);
      setReport(next.report);
      setDirty(false);
      setProblem(null);
    } catch (error) {
      setProblem(message(error, "The workflow could not be loaded."));
    }
  }, [graphPath, readJson, previewRequest, setView, setNodes, setReport, setDirty, setProblem]);
  useEffect(() => { void open(); }, [open]);
  useEffect(() => {
    readJson<Array<{ name?: string }>>(TOOL_CATALOG_PATH)
      .then((rows) => setToolNames(Array.isArray(rows) ? rows.flatMap((row) => (row.name ? [row.name] : [])) : []))
      .catch(() => setToolNames([]));
  }, [readJson, setToolNames]);

  // Every edit is previewed: the server re-derives modes, approvals and allowed tools and validates the definition.
  useEffect(() => {
    if (!dirty) return undefined;
    const request = ++previewRequest.current;
    const timer = window.setTimeout(() => applyStepsPreview(state, readJson, graphPath, request), PREVIEW_DELAY_MS);
    return () => window.clearTimeout(timer);
    // The preview reacts to the stored entries; its own result must not trigger another round.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(nodes.map((node) => node.step ?? node.check ?? null)), dirty]);
  return open;
}

// The canvas toolbar: "+ Step" and "+ Check" open the side panel with a draft; read-only shows why.
function StepsToolbar({ view, editable, state }: { view: StepsGraphView; editable: boolean; state: StepsWorkflowState }) {
  const { setSelectedId, setAdding } = state;
  return editable ? (
    <>
      <button type="button" className="admin-panel__action-btn" data-testid="steps-add-step"
        onClick={() => { setSelectedId(null); setAdding(newStep("")); }}>+ Step</button>
      <button type="button" className="admin-panel__action-btn" data-testid="steps-add-check"
        onClick={() => { setSelectedId(null); setAdding(newCheck(view.checkTypes[0] ?? "tool_called")); }}>+ Check</button>
    </>
  ) : <span>{view.readOnlyReason || "Read-only"}</span>;
}

export function StepsWorkflowEditor({ graphPath, readJson, onDirtyChange, onBack }: StepsWorkflowEditorProps) {
  const state = useStepsWorkflowState(onDirtyChange);
  const { view, nodes, report, dirty, busy, selectedId, setSelectedId, adding, setAdding, toolNames, problem, notice, setNodes,
    setDirty, setNotice } = state;
  const open = useStepsWorkflowLoading(state, readJson, graphPath);

  const edit = (next: StepsGraphNode[], select?: string | null) => {
    setNodes(next);
    setDirty(true);
    setNotice(null);
    if (select !== undefined) setSelectedId(select);
  };
  const context = { state, readJson, graphPath };

  if (!view) {
    return problem ? <p className="admin-panel__error" role="alert">{problem}</p>
      : <p className="admin-panel__hint" role="status">Loading the workflow…</p>;
  }
  const editable = view.editable;
  const selected = nodes.find((node) => node.id === selectedId) ?? null;
  const missingTool = nodes.some((node) => node.kind === "step" && !String(node.step?.tool ?? "").trim());

  return (
    <div className="flow-builder" data-testid="steps-workflow-editor">
      <StepsEditorHeader view={view} onBack={onBack} editable={editable} dirty={dirty} busy={busy}
        saveBlocked={missingTool || report?.valid === false}
        onDiscardChanges={() => { setSelectedId(null); void open(); }} onSave={() => void saveStepsDraft(context)} />
      <StepsEditorNotices problem={problem} notice={notice} dirty={dirty} missingTool={missingTool} report={report} />
      <div className="flow-builder__layout flow-builder__layout--editor">
        <main className="flow-builder__main">
          <div className="flow-builder__canvas-shell">
            <ReactFlowProvider>
              <StepsCanvas nodes={nodes} selectedNodeId={selectedId} onNodeSelect={setSelectedId}
                toolbar={<StepsToolbar view={view} editable={editable} state={state} />} />
            </ReactFlowProvider>
          </div>
        </main>
      </div>
      {adding ? (
        <StepsAddPanel adding={adding} setAdding={setAdding} view={view} editable={editable} toolNames={toolNames}
          onConfirm={() => { edit(insertNode(nodes, adding), null); setAdding(null); }} />
      ) : null}
      {selected ? (
        <StepsNodePanel selected={selected} nodes={nodes} edit={edit} setSelectedId={setSelectedId} view={view} editable={editable}
          toolNames={toolNames} />
      ) : null}
    </div>
  );
}
