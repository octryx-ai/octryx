// A workflow that runs in phases, opened from the Workflows list: a flow chart of its
// nodes and the results that lead from one to the next, laid out top to bottom, the one view of the workflow. Boxes
// can be dragged; "Save layout" stores where they are in a new draft version (never published here). Groups fold
// into one box without moving anything. A click on a box (or on a badge, for the box it leads to) explains it in a
// side panel; a phase opens in the Steps canvas (its steps and checks). A draft opens in the designer (D2b1,
// designer/DesignerEditor): built by hand, saved as a draft at any time; a published version stays read only until
// "Edit as draft" makes a draft of it. Folding re-lays the chart out; it is drawn top to bottom or left to right.
import { useCallback, type ReactNode } from "react";
import { ReactFlowProvider } from "@xyflow/react";

import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import "../../flowBuilder/flowBuilder.css";
import { DesignerEditor } from "./designer/DesignerEditor";
import { PhasedCanvas } from "./PhasedCanvas";
import { PhasedCanvasToolbar } from "./PhasedCanvasToolbar";
import { PhasedEditorHeader } from "./PhasedEditorHeader";
import { phasedEditorActions } from "./phasedEditorActions";
import { PhasedNodePanel } from "./PhasedNodePanel";
import { describeNode } from "./phasedNodeDetails";
import { designerEditable, phaseGraphPath, publishBlockReason, type PhasedView } from "./phasedWorkflowModel";
import { StepsWorkflowEditor } from "./StepsWorkflowEditor";
import { usePhasedEditorState, usePhasedLayout } from "./usePhasedEditor";
import "./workflowCanvas.css";

type PhasedWorkflowEditorProps = {
  flowId: string;
  readJson: ReadJsonFn;
  onDirtyChange?: (dirty: boolean) => void;
  // "← All workflows": back to the Workflows list.
  onBack?: () => void;
};

type EditorState = ReturnType<typeof usePhasedEditorState>;
type EditorLayout = ReturnType<typeof usePhasedLayout>;

export function PhasedWorkflowEditor({
  flowId,
  readJson,
  onDirtyChange,
  onBack,
}: PhasedWorkflowEditorProps) {
  const state = usePhasedEditorState(flowId, readJson);
  const { view, setView, openPhase, setOpenPhase, folded, setFolded, setBusy, problem, setProblem, setNotice, load } = state;
  const layoutState = usePhasedLayout(view, folded, onDirtyChange);
  const { layout, positions, unsavedLayout } = layoutState;
  const onFold = useCallback((groupId: string, fold: boolean) => {
    setFolded((current) => {
      const next = new Set(current);
      if (fold) next.add(groupId);
      else next.delete(groupId);
      return next;
    });
  }, [setFolded]);
  const onOpenPhase = useCallback((id: string) => {
    if (!unsavedLayout) setOpenPhase(id);
  }, [unsavedLayout, setOpenPhase]);

  const actions = phasedEditorActions({
    flowId, readJson, view, positions, layoutPositions: layout.positions, setBusy, setProblem, setNotice, setView, load,
  });

  if (openPhase) {
    return (
      <StepsWorkflowEditor graphPath={phaseGraphPath(flowId, openPhase)} readJson={readJson} onDirtyChange={onDirtyChange}
        onBack={() => { setOpenPhase(null); void load(); }} />
    );
  }
  if (!view) {
    return problem ? (
      <p className="admin-panel__error" role="alert">
        {problem}
      </p>
    ) : (
      <p className="admin-panel__hint" role="status">
        Loading the workflow…
      </p>
    );
  }
  if (designerEditable(view)) {
    return (
      <DesignerEditor view={view} readJson={readJson} onView={setView} onReload={load} onDirtyChange={onDirtyChange}
        onBack={onBack} onOpenPhase={setOpenPhase} />
    );
  }
  return (
    <PhasedReadOnlyView view={view} state={state} layoutState={layoutState} actions={actions} onBack={onBack} onFold={onFold}
      onOpenPhase={onOpenPhase} />
  );
}

type ReadOnlyProps = {
  view: PhasedView; state: EditorState; layoutState: EditorLayout; actions: ReturnType<typeof phasedEditorActions>;
  onBack?: () => void; onFold: (groupId: string, fold: boolean) => void; onOpenPhase: (id: string) => void;
};

// A published version: the chart read only, laid out and folded here, with its validation and node details.
function PhasedReadOnlyView({ view, state, layoutState, actions, onBack, onFold, onOpenPhase }: ReadOnlyProps) {
  const { selectedId, setSelectedId, setOpenPhase, busy, problem, notice } = state;
  const { graph, unsavedLayout } = layoutState;
  const { editAsDraft, publish } = actions;
  const report = view.validation_report;
  const blocked = publishBlockReason(view, { unsavedLayout, busy });
  const selected = selectedId ? view.nodes.find((node) => node.id === selectedId) ?? null : null;
  const details = selected ? describeNode(selected, view.edges, view.nodes) : null;
  const toolbar = <PhasedToolbar view={view} state={state} layoutState={layoutState} saveLayout={actions.saveLayout} />;

  return (
    <div className="flow-builder" data-testid="designer">
      <PhasedEditorHeader view={view} busy={busy} blocked={blocked} onBack={onBack}
        onEditAsDraft={() => void editAsDraft()} onPublish={() => void publish()} />
      {problem ? (
        <div className="admin-panel__error" role="alert">
          {problem}
        </div>
      ) : null}
      {notice ? (
        <div className="admin-panel__success" role="status">
          {notice}
        </div>
      ) : null}
      <PhasedIssues report={report} />
      <PhasedChart view={view} state={state} layoutState={layoutState} onFold={onFold} onOpenPhase={onOpenPhase}
        toolbar={toolbar} />
      {selected && details ? (
        <PhasedNodePanel selected={selected} details={details} unsavedLayout={unsavedLayout}
          onClose={() => setSelectedId(null)} onOpenSteps={() => { setSelectedId(null); setOpenPhase(selected.id); }} />
      ) : null}
    </div>
  );
}

type ToolbarProps = { view: PhasedView; state: EditorState; layoutState: EditorLayout; saveLayout: () => Promise<void> };

function PhasedToolbar({ view, state, layoutState, saveLayout }: ToolbarProps) {
  const { legendOpen, setLegendOpen, busy, folded, setFolded } = state;
  const { graph, unsavedLayout, setPositions, saved, direction, setChosenDirection, arranged, layout } = layoutState;
  const allFolded = graph.groups.length > 0 && graph.groups.every((group) => folded.has(group.id));
  return (
    <PhasedCanvasToolbar
      legendOpen={legendOpen}
      onToggleLegend={() => setLegendOpen((current) => !current)}
      editable={view.editable}
      unsavedLayout={unsavedLayout}
      busy={busy}
      onUndoMoves={() => setPositions(saved)}
      onSaveLayout={() => void saveLayout()}
      hasGroups={graph.groups.length > 0}
      allFolded={allFolded}
      onToggleFold={() => setFolded(allFolded ? new Set() : new Set(graph.groups.map((group) => group.id)))}
      direction={direction}
      onToggleDirection={() => setChosenDirection(direction === "lr" ? "tb" : "lr")}
      arranged={arranged}
      onAutoArrange={() => setPositions(new Map(layout.positions))}
    />
  );
}

function PhasedIssues({ report }: { report: PhasedView["validation_report"] }) {
  return (
    <>
    {report.errors.length || report.warnings.length ? (
      <ul className="aw-issues aw-issues--phased" aria-label="Validation">
        {report.errors.map((issue) => (
          <li
            key={`e-${issue.code}-${issue.message}`}
            className="admin-panel__error"
          >
            {issue.message}
          </li>
        ))}
        {report.warnings.map((issue) => (
          <li
            key={`w-${issue.code}-${issue.message}`}
            className="admin-panel__hint"
          >
            {issue.message}
          </li>
        ))}
      </ul>
    ) : null}
    </>
  );
}

type ChartProps = {
  view: PhasedView; state: EditorState; layoutState: EditorLayout; onFold: (groupId: string, fold: boolean) => void;
  onOpenPhase: (id: string) => void; toolbar: ReactNode;
};

function PhasedChart({ view, state, layoutState, onFold, onOpenPhase, toolbar }: ChartProps) {
  const { folded, busy, selectedId, setSelectedId } = state;
  const { graph, layout, positions, onMove } = layoutState;
  return (
    <div className="flow-builder__layout flow-builder__layout--editor">
      <main className="flow-builder__main">
        <div className="flow-builder__canvas-shell">
          <ReactFlowProvider>
            <PhasedCanvas
              graph={graph}
              layout={layout}
              positions={positions}
              folded={folded}
              onFold={onFold}
              editable={view.editable && !busy}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onMove={onMove}
              onOpenPhase={onOpenPhase}
              toolbar={toolbar}
            />
          </ReactFlowProvider>
        </div>
      </main>
    </div>
  );
}
