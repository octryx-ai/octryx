// Toolbar of the phased workflow chart: legend, moved boxes (undo, save layout), folding, direction, auto-arrange.
import type { LayoutDirection } from "./phasedGraphLayout";

type Props = {
  legendOpen: boolean;
  onToggleLegend: () => void;
  editable: boolean;
  unsavedLayout: boolean;
  busy: boolean;
  onUndoMoves: () => void;
  onSaveLayout: () => void;
  hasGroups: boolean;
  allFolded: boolean;
  onToggleFold: () => void;
  direction: LayoutDirection;
  onToggleDirection: () => void;
  arranged: boolean;
  onAutoArrange: () => void;
};

export function PhasedCanvasToolbar({ legendOpen, onToggleLegend, editable, unsavedLayout, busy, onUndoMoves, onSaveLayout,
  hasGroups, allFolded, onToggleFold, direction, onToggleDirection, arranged, onAutoArrange }: Props) {
  return (
  <>
    <span className="aw-pcanvas__legend">
      <button type="button" className="admin-panel__action-btn" aria-expanded={legendOpen} aria-controls="phased-legend"
        onClick={onToggleLegend}>
        {legendOpen ? "Hide legend" : "Legend"}
      </button>
      {legendOpen ? (
        <span id="phased-legend" className="aw-pcanvas__keys" aria-label="Legend">
          <i className="aw-pcanvas__key aw-pcanvas__key--agent" />Agent
          <i className="aw-pcanvas__key aw-pcanvas__key--action" />Platform
          <i className="aw-pcanvas__key aw-pcanvas__key--person" />Person
          <i className="aw-pcanvas__key aw-pcanvas__key--check" />Check
          <span className="aw-pbadge aw-pbadge--loop">↻ goes back</span>
          <span className="aw-pbadge aw-pbadge--failure">on failure →</span>
        </span>
      ) : null}
    </span>
    {editable && !unsavedLayout ? <span className="aw-pcanvas__hint">Drag boxes to arrange them</span> : null}
    {editable && unsavedLayout ? (
      <span className="aw-toolgroup" role="group" aria-label="Moved boxes">
        <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={onUndoMoves}>
          Undo moves
        </button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
          data-testid="phased-save-layout" onClick={onSaveLayout}
          title="Saves where the boxes are as a new draft version; nothing about how the workflow runs changes">
          Save layout
        </button>
      </span>
    ) : null}
    <span className="aw-toolgroup" role="group" aria-label="Layout">
    {hasGroups ? (
      <button type="button" className="admin-panel__action-btn"
        onClick={onToggleFold}
        title="Show each phase with its checks as one box, or every box again; nothing moves">
        {allFolded ? "Unfold groups" : "Fold groups"}
      </button>
    ) : null}
    <button type="button" className="admin-panel__action-btn" onClick={onToggleDirection}
      title="Draw the workflow top to bottom or left to right">{direction === "lr" ? "Top to bottom" : "Left to right"}</button>
    {editable ? (
      <button type="button" className="admin-panel__action-btn" disabled={busy || arranged}
        onClick={onAutoArrange} title="Put every box back where the automatic layout draws it">
        Auto-arrange
      </button>
    ) : null}
    </span>
  </>
  );
}
