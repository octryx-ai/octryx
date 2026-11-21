// The designer's top bar: the way back, the workflow's name and status, and Save draft, Request publishing and Publish.
import { StatusLabel } from "../../../../../layout/StatusLabel";
import { designerStatus, phasedStatusLabel, publishBlockReason, type PhasedView } from "../phasedWorkflowModel";

export function DesignerHeader({ view, title, setTitle, dirty, busy, onBack, save, requestPublishing, publish }: {
  view: PhasedView;
  title: string;
  setTitle: (title: string) => void;
  dirty: boolean;
  busy: boolean;
  onBack?: () => void;
  save: () => Promise<unknown>;
  requestPublishing: () => Promise<unknown>;
  publish: () => Promise<unknown>;
}) {
  const inReview = view.review_state === "awaiting_approval";
  const requestBlocked = dirty ? "Save the draft first."
    : !view.validation_report.valid ? "Fix the problems listed above first."
      : inReview ? "Already waiting for another admin." : "";
  const blocked = publishBlockReason(view, { unsavedLayout: dirty, busy }).replace("Save or undo the moved boxes first.", "Save the draft first.")
    || (view.can_publish === false ? view.publish_reason || "A second admin publishes this version." : "");
  const status = designerStatus(view);
  return (
    <div className="flow-builder__topbar">
      {onBack ? <button type="button" className="admin-panel__action-btn flow-builder__back" onClick={onBack}>← All workflows</button> : null}
      <div className="flow-builder__title-block">
        <span className="admin-panel__eyebrow">Workflow · Runs in phases</span>
        <div className="flow-builder__title-row">
          <input className="admin-panel__input dsg__name" data-testid="designer-name" aria-label="Name of the workflow" value={title}
            onChange={(event) => setTitle(event.target.value)} />
          <span data-testid="designer-status" data-status={status}>
            <StatusLabel label={status === "in review" ? `In review · draft v${view.version}` : phasedStatusLabel(view)}
              tone={status === "published" ? "neutral" : "attention"} />
          </span>
        </div>
      </div>
      <div className="flow-builder__header-actions">
        <button type="button" className="admin-panel__action-btn" data-testid="designer-save-draft" disabled={busy || !dirty}
          title={dirty ? "Store the workflow as a draft; it may still be incomplete" : "Nothing changed since the last save"}
          onClick={() => void save()}>Save draft</button>
        <button type="button" className="admin-panel__action-btn" data-testid="designer-request-publish"
          disabled={busy || Boolean(requestBlocked)} title={requestBlocked || "Ask another admin to check and publish this version"}
          onClick={() => void requestPublishing()}>Request publishing</button>
        {blocked ? <span className="admin-panel__hint aw-publish-reason" data-testid="phased-publish-reason" title={blocked}>{blocked}</span> : null}
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={Boolean(blocked) || busy}
          title={blocked || "Make this version the one new runs use"} onClick={() => void publish()}>Publish</button>
      </div>
    </div>
  );
}
