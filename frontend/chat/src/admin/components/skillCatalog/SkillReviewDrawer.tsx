import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { hasOpenConflicts } from "./skillCatalogModel";
import { SkillReviewerSection } from "./SkillReviewerSection";
import { ReviewChanges, ReviewSummary, ReviewTimeline } from "./SkillReviewParts";
import { reviewAction } from "./skillUpdateModel";
import { skillReviewActions, useSkillReview } from "./useSkillReview";

const ACTION_LABELS = { submit: "Submit for review", approve: "Approve", publish: "Publish", publish_own: "Publish" } as const;

// Review and publish (mock `renderReview` / `#drawer-review`): the four-eyes lifecycle of the skill's open
// version — Draft → In review → Published — with the summary, the full diff against the published version and the
// reviewer section. Approve is offered only when the server says this viewer may approve (`review.viewer.can_approve`);
// publishing needs the approved review; the server enforces both (refusals are shown as they come). Under the
// single-admin approval rule the author publishes in one step (submit + self-approve + publish).
export function SkillReviewDrawer({ skillId, onClose, onChanged }: { skillId: string; onClose: () => void; onChanged: () => void }) {
  const state = useSkillReview(skillId);
  const { detail, diff, note, setNote, busy, problem, done, selfApproval, version } = state;
  const { run, reject } = skillReviewActions(state, skillId, onChanged);

  const review = detail?.review ?? null;
  const published = detail?.published ?? null;
  const action = reviewAction(version, review, selfApproval);
  const blocked = version ? hasOpenConflicts(version.merge_report) : false;

  const shown = version ?? published;
  const footer = (
    <>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
      {action ? (
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid={`skill-review-${action}`}
          disabled={busy || (action !== "approve" && action !== "publish" && blocked)}
          title={action !== "approve" && action !== "publish" && blocked ? "Resolve every conflict first" : undefined}
          onClick={() => void run[action]()}>{ACTION_LABELS[action]}</button>
      ) : null}
    </>
  );

  return (
    <SettingsDrawer eyebrow={detail ? `${detail.name}${shown ? ` · v${shown.version}` : ""}` : "Skill"} title="Review and publish"
      size="detail" onClose={onClose} footer={footer}>
      <div className="policies__pane" data-testid="skill-review-drawer">
        {problem ? <p className="workspace-classification__message" role="alert" data-testid="skill-review-problem">{problem}</p> : null}
        {done ? <p className="admin-panel__hint" role="status" data-testid="skill-review-done">{done}</p> : null}
        {!detail ? (problem ? null : <p className="admin-panel__hint" role="status">Loading…</p>) : !shown ? (
          <p className="admin-panel__hint">This skill has no open or published version.</p>
        ) : (
          <>
            <ReviewTimeline version={version} published={published} review={review} shown={shown} blocked={blocked} selfApproval={selfApproval} />
            {!version ? <div className="policies__note">v{shown.version} is published; there is no open draft to review.</div> : (
              <>
                <ReviewSummary version={version} detail={detail} diff={diff} />
                <ReviewChanges published={published} diff={diff} />
                <SkillReviewerSection version={version} review={review} note={note} busy={busy} selfApproval={selfApproval}
                  onNote={setNote} onReject={(reason) => void reject(reason)} />
              </>
            )}
          </>
        )}
      </div>
    </SettingsDrawer>
  );
}
