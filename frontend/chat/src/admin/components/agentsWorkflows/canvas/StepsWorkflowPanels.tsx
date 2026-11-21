// The phase steps editor's notices and side panels: problems, the unsaved hint and the validation issues; the panel
// for a new step or check and the panel of a selected node.
import type { Dispatch, SetStateAction } from "react";
import { SidePanel } from "../../../../layout/SidePanel";
import { ActionMenu } from "../../workflowSurfaces/ActionMenu";
import { StepsInspector } from "./StepsInspector";
import {
  canvasNode, moveNode, patchNode, removeNode, updateCheck, updateStep, type StepsGraphNode, type StepsGraphView,
  type ValidationReport,
} from "./stepsGraphModel";

const stored = (node: StepsGraphNode) => !node.derived && (node.kind === "step" || node.kind === "check");

export function StepsEditorNotices({ problem, notice, dirty, missingTool, report }: {
  problem: string | null;
  notice: string | null;
  dirty: boolean;
  missingTool: boolean;
  report: ValidationReport | null;
}) {
  return (
    <>
      {problem ? <div className="admin-panel__error" role="alert">{problem}</div> : null}
      {notice ? <div className="admin-panel__success" role="status">{notice}</div> : null}
      {dirty ? (
        <p className="admin-panel__hint" role="status">
          {missingTool ? "Every step needs a tool before the draft can be saved."
            : "Unsaved changes — save them as a draft version of the workflow."}
        </p>
      ) : null}
      {report && (report.errors.length || report.warnings.length) ? (
        <ul className="aw-issues" aria-label="Validation">
          {report.errors.map((issue) => <li key={`e-${issue.code}-${issue.message}`} className="admin-panel__error">{issue.message}</li>)}
          {report.warnings.map((issue) => <li key={`w-${issue.code}-${issue.message}`} className="admin-panel__hint">{issue.message}</li>)}
        </ul>
      ) : null}
    </>
  );
}

export function StepsAddPanel({ adding, setAdding, onConfirm, view, editable, toolNames }: {
  adding: StepsGraphNode;
  setAdding: Dispatch<SetStateAction<StepsGraphNode | null>>;
  onConfirm: () => void;
  view: StepsGraphView;
  editable: boolean;
  toolNames: string[];
}) {
  return (
    <SidePanel
      title={adding.kind === "step" ? "Add step" : "Add check"}
      onClose={() => setAdding(null)}
      testId="steps-add-panel"
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={() => setAdding(null)}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="steps-add-confirm"
            disabled={adding.kind === "step" && !String(adding.step?.tool ?? "").trim()}
            onClick={onConfirm}>
            {adding.kind === "step" ? "Add step" : "Add check"}
          </button>
        </>
      )}
    >
      <StepsInspector
        node={adding} view={view} editable={editable} toolNames={toolNames}
        onStep={(patch) => setAdding((current) => (current ? patchNode(current, patch) : current))}
        onCheck={(patch) => setAdding((current) => (current ? patchNode(current, patch) : current))}
      />
    </SidePanel>
  );
}

export function StepsNodePanel({ selected, nodes, edit, setSelectedId, view, editable, toolNames }: {
  selected: StepsGraphNode;
  nodes: StepsGraphNode[];
  edit: (next: StepsGraphNode[], select?: string | null) => void;
  setSelectedId: (id: string | null) => void;
  view: StepsGraphView;
  editable: boolean;
  toolNames: string[];
}) {
  return (
    <SidePanel
      title={canvasNode(selected).label || "Step settings"}
      subtitle={selected.kind === "step" ? "Step" : selected.kind === "check" ? "Check" : "Derived from the definition"}
      onClose={() => setSelectedId(null)}
      testId="steps-node-panel"
      headerActions={editable && stored(selected) ? (
        <ActionMenu row={{ objectName: canvasNode(selected).label || "this node" }} items={[
          { label: "Remove", danger: true, testId: "steps-node-remove", onSelect: () => edit(removeNode(nodes, selected.id), null) },
        ]} />
      ) : null}
      footer={(
        <>
          {editable && stored(selected) ? (
            <>
              <button type="button" className="admin-panel__action-btn" onClick={() => edit(moveNode(nodes, selected.id, -1))}>Move earlier</button>
              <button type="button" className="admin-panel__action-btn" onClick={() => edit(moveNode(nodes, selected.id, 1))}>Move later</button>
            </>
          ) : null}
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={() => setSelectedId(null)}>Done</button>
        </>
      )}
    >
      <StepsInspector
        node={selected} view={view} editable={editable} toolNames={toolNames}
        onStep={(patch) => edit(updateStep(nodes, selected.id, patch))}
        onCheck={(patch) => edit(updateCheck(nodes, selected.id, patch))}
      />
    </SidePanel>
  );
}
