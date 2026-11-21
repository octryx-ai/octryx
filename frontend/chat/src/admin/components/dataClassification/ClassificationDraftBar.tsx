import type { VersionsView } from "./classificationVersionsModel";
import { draftBarText } from "./classificationVersionsModel";

// The draft bar (mock): what the open draft changes and the next step of its review.
export function ClassificationDraftBar({ view, busy, onReview, onSubmit, onDiscard, onApprove, onReject }: {
  view: VersionsView;
  busy: boolean;
  onReview: () => void;
  onSubmit: () => void;
  onDiscard: () => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const draft = view.draft;
  const inReview = draft?.state === "in_review";
  return (
    <div className="sk-draftbar" data-testid="classification-draftbar">
      <div className="sk-row">
        <span className={`work-badge ${inReview ? "work-badge--running" : "work-badge--attention"}`}>{inReview ? "In review" : "Draft"}</span>
        <span data-testid="classification-draft-text"><strong>{draftBarText(view)}</strong></span>
      </div>
      <div className="sk-row">
        <button type="button" className="admin-panel__action-btn" onClick={onReview}>Review changes</button>
        {draft && !inReview ? (
          <>
            <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid="classification-discard" onClick={onDiscard}>Discard</button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !draft.changes.length}
              data-testid="classification-submit" onClick={onSubmit}>Submit for review</button>
          </>
        ) : null}
        {inReview ? (
          <>
            <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid="classification-withdraw" onClick={onDiscard}>Withdraw</button>
            {draft?.review?.canApprove ? (
              <>
                <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid="classification-reject" onClick={onReject}>Reject</button>
                <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
                  data-testid="classification-approve" onClick={onApprove}>Approve and publish</button>
              </>
            ) : null}
          </>
        ) : null}
        {!draft ? (
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled data-testid="classification-submit">
            Submit for review
          </button>
        ) : null}
      </div>
    </div>
  );
}
