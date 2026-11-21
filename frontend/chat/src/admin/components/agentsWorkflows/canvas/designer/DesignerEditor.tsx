// The workflow designer's editing mode (D2b1): a draft of a workflow that runs in phases, drawn by hand. The box
// catalog on the left (drag or click), the flow chart in the middle (connect a box's out port to another box; a click
// selects a box or an arrow), the side panel on the right (octryx-pet's NodeInspector / EdgeInspector). Every change
// goes into the model (designer/model.ts) and can be undone; "Save draft" stores the whole definition as a new draft
// version at any time, also while it is incomplete; the problem list says what is missing and selects its box.
import { useCallback } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import type { ReadJsonFn } from "../../../../hooks/useAdminTabLoader.types";
import { PhasedCanvas } from "../PhasedCanvas";
import type { Point } from "../phasedGraphTypes";
import type { PhasedView } from "../phasedWorkflowModel";
import { DesignerBoxMenu } from "./DesignerBoxMenu";
import { DesignerCatalogPanel } from "./DesignerCatalogPanel";
import { DesignerHeader } from "./DesignerHeader";
import { DesignerIssues } from "./DesignerIssues";
import { createDesignerPublishing } from "./designerPublishing";
import { designerSidePanel } from "./designerSidePanel";
import { DesignerToolbar } from "./DesignerToolbar";
import { findEdge, findNode } from "./modelCore";
import { moveNodes } from "./modelEditing";
import { useDesignerCanvasEditing } from "./useDesignerCanvasEditing";
import {
  useDesignerAddConnect, useDesignerCatalog, useDesignerChart, useDesignerDraft, useDesignerIssues, useDesignerSelection,
} from "./useDesignerEditorState";
import { useDesignerSelectionActions } from "./useDesignerSelectionActions";
import { useDesignerShortcuts } from "./useDesignerShortcuts";

type DesignerEditorProps = {
  view: PhasedView;
  readJson: ReadJsonFn;
  // The version the server now has (after a save or a publish).
  onView: (view: PhasedView) => void;
  onReload: () => Promise<void>;
  onDirtyChange?: (dirty: boolean) => void;
  onBack?: () => void;
  onOpenPhase: (id: string) => void;
};

// Every state, derived view and action of the designer, in the order the editor's hooks run.
function useDesignerEditor({ view, readJson, onView, onReload, onDirtyChange }: DesignerEditorProps) {
  const draft = useDesignerDraft(view, onDirtyChange);
  const { setHistory, model, named } = draft;
  const messages = useDesignerCatalog(readJson, view);
  const { catalog, setProblem, setNotice, setBusy } = messages;
  const selection = useDesignerSelection(setHistory);
  const { selected, setSelected, edgeId, setEdgeId, setGroupId, setMenu, folded, setFolded, clip, focus, change, selectOnly } = selection;

  // --- The chart and its problems -----------------------------------------------------------------------------------
  const chart = useDesignerChart(model, folded, selection.shownRef);
  const issues = useDesignerIssues(model, catalog, view);

  // --- Changes ------------------------------------------------------------------------------------------------------
  const { addBox, connectBoxes } = useDesignerAddConnect({ model, catalog, chart, selection, setProblem });
  const actions = useDesignerSelectionActions({
    model, positions: chart.positions, currentGroups: chart.currentGroups, selection, setHistory, setNotice,
  });
  const { deleteSelection, copySelection, pasteClip, doUndo, doRedo } = actions;

  useDesignerShortcuts({ deleteSelection, doUndo, doRedo, copySelection, pasteClip, selected, clip });

  // --- Saving and publishing ----------------------------------------------------------------------------------------
  const publishing = createDesignerPublishing({
    readJson, view, model, named, onView, onReload, setBusy, setProblem, setNotice,
  });

  // --- The canvas's editing hooks -----------------------------------------------------------------------------------
  const editing = useDesignerCanvasEditing({ selected, edgeId, focus, selectOnly, connectBoxes, addBox, setSelected, setEdgeId,
    setGroupId, setMenu });

  const onMove = useCallback((moves: Array<[string, Point]>) => change((current) => moveNodes(current, moves)), [change]);
  const onFold = useCallback((id: string, fold: boolean) => setFolded((current) => {
    const next = new Set(current);
    if (fold) next.add(id);
    else next.delete(id);
    return next;
  }), [setFolded]);
  return { ...draft, ...messages, selection, chart, issues, addBox, connectBoxes, actions, ...publishing, editing, onMove, onFold };
}

type DesignerEditorModel = ReturnType<typeof useDesignerEditor>;

// The canvas toolbar: undo and redo, the clipboard, groups and folding, the direction and the legend.
function DesignerChartToolbar({ editor }: { editor: DesignerEditorModel }) {
  const { history, model, selection, chart, actions } = editor;
  const { legendOpen, setLegendOpen, selected, clip, folded, setFolded, change } = selection;
  const { selectedNodes, doUndo, doRedo, copySelection, pasteClip, deleteSelection, groupSelection, groupOfSelection, ungroup } = actions;
  const { graph, direction } = chart;
  const edge = findEdge(model, selection.edgeId);
  const allFolded = graph.groups.length > 0 && graph.groups.every((item) => folded.has(item.id));
  return (
    <DesignerToolbar legendOpen={legendOpen} setLegendOpen={setLegendOpen} history={history} doUndo={doUndo} doRedo={doRedo}
      selectedNodes={selectedNodes} selected={selected} clip={clip} edge={edge} copySelection={copySelection}
      pasteClip={pasteClip} deleteSelection={deleteSelection} groupSelection={groupSelection}
      groupOfSelection={groupOfSelection} ungroup={ungroup} groups={graph.groups} allFolded={allFolded}
      setFolded={setFolded} direction={direction} model={model} change={change} />
  );
}

// The box catalog, the chart with the box menu, and the side panel of the selection.
function DesignerWorkspace({ editor, view, onOpenPhase }: { editor: DesignerEditorModel; view: PhasedView; onOpenPhase: (id: string) => void }) {
  const { model, catalog, busy, dirty, selection, chart, addBox, connectBoxes, actions, editing, onMove, onFold } = editor;
  const { edgeId, groupId, menu, setMenu, folded, change, selectOnly } = selection;
  const { graph, currentGroups, layout, positions } = chart;
  const { selectedNodes, copySelection, deleteSelection, groupSelection, ungroup } = actions;

  // --- The side panel -----------------------------------------------------------------------------------------------
  const node = selectedNodes.length === 1 ? selectedNodes[0] : null;
  const edge = findEdge(model, edgeId);
  const group = groupId ? currentGroups.find((item) => item.id === groupId) ?? null : null;
  const menuNode = menu ? findNode(model, menu.id) : undefined;
  const closePanel = () => selectOnly([]);
  const panel = designerSidePanel({
    node, edge, group, selectedNodes, model, catalog, view, busy, dirty, currentGroups, change, closePanel,
    copySelection, deleteSelection, groupSelection, ungroup, onOpenPhase,
  });

  return (
    <div className="dsg">
      <DesignerCatalogPanel onAdd={(kind) => addBox(kind)} disabled={busy} />
      <main className="dsg__main flow-builder__main">
        <div className="flow-builder__canvas-shell">
          <ReactFlowProvider>
            <PhasedCanvas graph={graph} layout={layout} positions={positions} folded={folded} onFold={onFold} editable={!busy}
              selectedId={node?.id ?? null} onSelect={(id) => selectOnly(id ? [id] : [])} onMove={onMove}
              onOpenPhase={onOpenPhase} toolbar={<DesignerChartToolbar editor={editor} />} edit={editing} />
          </ReactFlowProvider>
        </div>
        {menu && menuNode ? (
          <DesignerBoxMenu menu={menu} menuNode={menuNode} model={model} connectBoxes={connectBoxes} setMenu={setMenu}
            copySelection={copySelection} deleteSelection={deleteSelection} />
        ) : null}
      </main>
      {panel ? <aside className="dsg__panel" aria-label="Settings">{panel}</aside> : null}
    </div>
  );
}

export function DesignerEditor(props: DesignerEditorProps) {
  const { view, onBack, onOpenPhase } = props;
  const editor = useDesignerEditor(props);
  const { title, setTitle, dirty, busy, problem, notice, issues, selection, editing, save, requestPublishing, publish } = editor;
  const { issuesOpen, setIssuesOpen, selectOnly, setFocus } = selection;

  return (
    <div className="flow-builder" data-testid="designer">
      <DesignerHeader view={view} title={title} setTitle={setTitle} dirty={dirty} busy={busy} onBack={onBack} save={save}
        requestPublishing={requestPublishing} publish={publish} />
      {problem ? <div className="admin-panel__error" role="alert">{problem}</div> : null}
      {notice ? <div className="admin-panel__success" role="status">{notice}</div> : null}
      <DesignerIssues issues={issues} issuesOpen={issuesOpen} setIssuesOpen={setIssuesOpen} dirty={dirty}
        onSelectEdge={(id) => editing.onSelectEdge(id)}
        onSelectNode={(id) => {
          selectOnly([id]);
          setFocus({ id, nonce: Date.now() });
        }} />
      <DesignerWorkspace editor={editor} view={view} onOpenPhase={onOpenPhase} />
    </div>
  );
}
