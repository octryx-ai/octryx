import { useState } from "react";

import type { Review, SkillVersion } from "./skillCatalogTypes";
import { names, waitingReason } from "./skillUpdateModel";

// The reviewer section of the review drawer: for a draft the optional note for the reviewer; in review the
// four-eyes review as the server reports it — who requested it, the rule, who may approve — and, only for a viewer
// with `can_approve`, rejecting with a reason. Authors and submitters see whom they wait for and why.
export function SkillReviewerSection({ version, review, note, busy, selfApproval = false, onNote, onReject }: {
  version: SkillVersion;
  /** The single-admin approval rule: the author approves and publishes in one step. */
  selfApproval?: boolean;
  review: Review | null;
  note: string;
  busy: boolean;
  onNote: (note: string) => void;
  onReject: (reason: string) => void;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  if (version.state === "draft") {
    return (
      <section className="work-detail__section" data-testid="skill-review-reviewer">
        <h3>Reviewer</h3>
        <p className="skills__hint" data-testid="skill-review-draft-rule">{selfApproval
          ? "The approval rule lets you approve and publish your own version in one step; it is recorded as self-approved. Publishing freezes this draft."
          : "A platform admin other than the author and the submitter must approve before anyone can publish. Submitting freezes this draft."}</p>
        <label className="admin-panel__field"><span>Note for the reviewer</span>
          <textarea rows={2} maxLength={500} value={note} data-testid="skill-review-note" onChange={(event) => onNote(event.target.value)} /></label>
      </section>
    );
  }
  if (!review) {
    return (
      <section className="work-detail__section" data-testid="skill-review-reviewer">
        <h3>Reviewer</h3>
        <p className="skills__hint">The review for this version could not be found.</p>
      </section>
    );
  }
  const canApprove = review.viewer.can_approve && review.status === "pending";
  return (
    <section className="work-detail__section" data-testid="skill-review-reviewer">
      <h3>Reviewer</h3>
      <dl className="work-detail__kv">
        <dt>Requested by</dt><dd>{review.requested_by?.name ?? "—"}</dd>
        {review.author ? (<><dt>Author</dt><dd>{review.author.name}</dd></>) : null}
        <dt>Status</dt><dd>{review.status}{review.decided_by ? ` by ${review.decided_by.name}` : ""}</dd>
        <dt>May approve</dt><dd>{names(review.approver_candidates)}</dd>
        {version.note ? (<><dt>Note</dt><dd>{version.note}</dd></>) : null}
      </dl>
      <div className="policies__note" data-testid="skill-review-rule">{review.rule}</div>
      {review.status === "approved" ? (
        <p className="skills__hint">Approved. Publishing makes v{version.version} live; octryx-claude sessions get it at their next start.</p>
      ) : review.status === "rejected" ? (
        <p className="skills__hint">Rejected{review.comment ? `: ${review.comment}` : "."}</p>
      ) : canApprove ? (
        <>
          <p className="skills__hint">You did not author or submit this version, so you can approve it.</p>
          {rejecting ? (
            <div className="admin-panel__stack">
              <label className="admin-panel__field"><span>Reason for rejecting</span>
                <textarea rows={2} value={reason} data-testid="skill-review-reject-reason" onChange={(event) => setReason(event.target.value)} /></label>
              <div className="policies__row">
                <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" data-testid="skill-review-reject-confirm"
                  disabled={busy || !reason.trim()} onClick={() => onReject(reason.trim())}>Reject</button>
                <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setRejecting(false)}>Cancel</button>
              </div>
            </div>
          ) : (
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" data-testid="skill-review-reject"
              disabled={busy} onClick={() => setRejecting(true)}>Reject…</button>
          )}
        </>
      ) : selfApproval && review.status === "pending" ? (
        <p className="skills__hint" data-testid="skill-review-self">The approval rule lets you approve and publish this version yourself.</p>
      ) : (
        <p className="skills__hint" data-testid="skill-review-waiting">
          Waiting for {names(review.approver_candidates)}. {waitingReason(review)}
          {review.single_admin ? " There is no second platform admin yet." : ""}
        </p>
      )}
    </section>
  );
}
