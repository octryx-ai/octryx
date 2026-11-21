// The designer chart's toolbar: legend, history, selection, groups and layout buttons.
import type { Dispatch, SetStateAction } from "react";

import type { GraphGroup } from "../phasedGraphTypes";
import { removable } from "./modelEditing";
import { setDirection } from "./modelDefinition";
import { type Clipboard } from "./modelClipboard";
import { type DesignModel } from "./modelCore";
import { type History } from "./modelHistory";
import type { DefEdge, DefNode } from "./types";

export function DesignerToolbar({
  legendOpen, setLegendOpen, history, doUndo, doRedo, selectedNodes, selected, clip, edge, copySelection, pasteClip,
  deleteSelection, groupSelection, groupOfSelection, ungroup, groups, allFolded, setFolded, direction, model, change,
}: {
  legendOpen: boolean; setLegendOpen: Dispatch<SetStateAction<boolean>>; history: History;
  doUndo: () => void; doRedo: () => void; selectedNodes: DefNode[]; selected: ReadonlySet<string>;
  clip: Clipboard | null; edge: DefEdge | undefined; copySelection: () => void; pasteClip: () => void;
  deleteSelection: () => void; groupSelection: () => void; groupOfSelection: string | null; ungroup: () => void;
  groups: GraphGroup[]; allFolded: boolean; setFolded: Dispatch<SetStateAction<ReadonlySet<string>>>;
  direction: string; model: DesignModel;
  change: (update: (current: DesignModel) => DesignModel, key?: string) => void;
}) {
  return (
    <>
      <span className="aw-pcanvas__legend">
        <button type="button" className="admin-panel__action-btn" aria-expanded={legendOpen} aria-controls="designer-legend"
          onClick={() => setLegendOpen((current) => !current)}>{legendOpen ? "Hide legend" : "Legend"}</button>
        {legendOpen ? (
          <span id="designer-legend" className="aw-pcanvas__keys" aria-label="Legend">
            <i className="aw-pcanvas__key aw-pcanvas__key--agent" />Agent
            <i className="aw-pcanvas__key aw-pcanvas__key--action" />Platform
            <i className="aw-pcanvas__key aw-pcanvas__key--person" />Person
            <i className="aw-pcanvas__key aw-pcanvas__key--check" />Check
            <span className="aw-pbadge aw-pbadge--loop">↻ goes back</span>
            <span>Drag from the dot under a box to the next box to connect them.</span>
          </span>
        ) : null}
      </span>
      <span className="aw-toolgroup" role="group" aria-label="History">
      <button type="button" className="admin-panel__action-btn" disabled={!history.past.length} onClick={doUndo} title="Undo (Ctrl+Z / ⌘Z)">Undo</button>
      <button type="button" className="admin-panel__action-btn" disabled={!history.future.length} onClick={doRedo} title="Redo (Ctrl+Shift+Z / ⌘⇧Z)">Redo</button>
      </span>
      <span className="aw-toolgroup" role="group" aria-label="Selection">
      <button type="button" className="admin-panel__action-btn" disabled={!selectedNodes.some(removable)} onClick={copySelection} title="Copy (Ctrl+C / ⌘C)">Copy</button>
      <button type="button" className="admin-panel__action-btn" disabled={!clip} onClick={pasteClip} title="Paste (Ctrl+V / ⌘V)">Paste</button>
      <button type="button" className="admin-panel__action-btn" disabled={!selectedNodes.some(removable) && !edge} onClick={deleteSelection}
        title="Delete (Delete key)">Delete</button>
      </span>
      <span className="aw-toolgroup" role="group" aria-label="Groups">
      <button type="button" className="admin-panel__action-btn" disabled={!selected.size} onClick={groupSelection}
        title="Group the selected boxes (Shift+click selects several)">Group</button>
      <button type="button" className="admin-panel__action-btn" disabled={!groupOfSelection} onClick={ungroup}>Ungroup</button>
      {groups.length ? (
        <button type="button" className="admin-panel__action-btn"
          onClick={() => setFolded(allFolded ? new Set() : new Set(groups.map((item) => item.id)))}>
          {allFolded ? "Unfold groups" : "Fold groups"}
        </button>
      ) : null}
      </span>
      <span className="aw-toolgroup" role="group" aria-label="Layout">
      <button type="button" className="admin-panel__action-btn" onClick={() => change((current) => setDirection(current, direction === "lr" ? "tb" : "lr"))}
        title="Draw the workflow top to bottom or left to right">{direction === "lr" ? "Top to bottom" : "Left to right"}</button>
      <button type="button" className="admin-panel__action-btn" disabled={!Object.keys(model.positions).length}
        onClick={() => change((current) => ({ ...current, positions: {} }))} title="Put every box back where the automatic layout draws it">
        Auto-arrange
      </button>
      </span>
    </>
  );
}
