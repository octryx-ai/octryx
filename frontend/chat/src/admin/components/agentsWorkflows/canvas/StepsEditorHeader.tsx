// The top bar of the phase steps editor: title, class and status, the way back to the phases, and the draft actions
// (the workflow publishes, not the phase).
import { Badge, ClassBadge } from "../awBadges";
import { stepsStatusLabel, type StepsGraphView } from "./stepsGraphModel";

type StepsEditorHeaderProps = {
  view: StepsGraphView;
  onBack: () => void;
  editable: boolean;
  dirty: boolean;
  busy: boolean;
  // A step without a tool or a refused validation keeps Save draft disabled.
  saveBlocked: boolean;
  onDiscardChanges: () => void;
  onSave: () => void;
};

export function StepsEditorHeader({
  view, onBack, editable, dirty, busy, saveBlocked, onDiscardChanges, onSave,
}: StepsEditorHeaderProps) {
  return (
    <div className="flow-builder__topbar">
      <div className="flow-builder__title-block">
        <span className="admin-panel__eyebrow">Workflow · Runs in phases · Phase</span>
        <div className="flow-builder__title-row">
          <h2 title={view.title || view.key}>{view.title || view.key}</h2>
          <ClassBadge value={view.graph.capabilityClass} />
          <Badge kind={view.status === "published" ? "active" : "attention"}>{stepsStatusLabel(view)}</Badge>
        </div>
      </div>
      <div className="flow-builder__header-actions">
        <button type="button" className="admin-panel__action-btn" onClick={onBack}>← Phases</button>
        {editable ? (
          <>
            <button type="button" className="admin-panel__action-btn" disabled={!dirty || busy}
              onClick={onDiscardChanges}>Discard changes</button>
            <button type="button" className="admin-panel__action-btn" disabled={!dirty || busy || saveBlocked}
              onClick={onSave}>Save draft</button>
          </>
        ) : null}
      </div>
    </div>
  );
}
