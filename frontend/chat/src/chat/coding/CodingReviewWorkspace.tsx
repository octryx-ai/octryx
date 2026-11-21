// The file review workspace of a coding session: files, review events, the editor and the feedback form.
import type { ReactNode } from "react";

import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import { reviewFileView, saveReviewFeedback, useReviewWorkspaceState } from "./codingReviewFeedback";
import { DEFAULT_FORM, buildFeedbackContext } from "./codingReviewWorkspaceModel";
import { ReviewEditor, ReviewFeedbackContext, ReviewFeedbackForm, ReviewFileList } from "./CodingReviewWorkspaceParts";

type CodingReviewWorkspaceProps = {
  session: CodingSessionSummary;
  detail: CodingSessionDetailData | null;
  latestPlan: WorkChangePlan | null;
  // Opens the Reviews tab, where the review decision is recorded.
  onOpenReviews?: () => void;
};

function NoReviewFiles({ reviewsLink }: { reviewsLink: ReactNode }) {
  return (
    <div className="work-empty">
      <div className="work-empty__eyebrow">No files</div>
      <h2>No planned file target is available for file feedback.</h2>
      <p>File comments need a planned file. A review decision needs none.</p>
      {reviewsLink}
    </div>
  );
}

export function CodingReviewWorkspace({ session, detail, latestPlan, onOpenReviews }: CodingReviewWorkspaceProps) {
  const { events, setEvents, selectedFile, setSelectedFile, form, setForm, saving, setSaving, error, setError, files } =
    useReviewWorkspaceState(session, detail, latestPlan);

  const view = reviewFileView(session, detail?.changeUnits || [], events, selectedFile, form);
  const { selectedChangeUnit, fileEvents, editorContent, canSave } = view;
  const feedbackContext = buildFeedbackContext(events, detail?.reviewEventsPayload?.agent_feedback_context);

  async function saveFeedback() {
    if (!canSave || saving) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await saveReviewFeedback({
        sessionId: session.id, selectedFile, changeUnitId: selectedChangeUnit?.id || null, editorContent, form,
      });
      setEvents((current) => [...current, created]);
      setForm(DEFAULT_FORM);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Feedback could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  // The decision itself lives in Reviews; Changes only points there.
  const reviewsLink = onOpenReviews ? (
    <p className="work-detail__empty">
      Approve, request changes or reject the work in Reviews.{" "}
      <button type="button" className="work-area__button" onClick={onOpenReviews}>Open Reviews</button>
    </p>
  ) : null;

  if (files.length === 0) {
    return <NoReviewFiles reviewsLink={reviewsLink} />;
  }

  return (
    <div className="coding-review" aria-label="Coding Review Workspace">
      <ReviewFileList files={files} events={events} fileEvents={fileEvents} selectedFile={selectedFile} setSelectedFile={setSelectedFile} />

      <ReviewEditor session={session} selectedFile={selectedFile} selectedChangeUnit={selectedChangeUnit}
        latestHumanEdit={view.latestHumanEdit} manualEdit={form.eventType === "manual_edit"}
        editorContent={editorContent} modifiedContent={view.modifiedContent} />

      <aside className="coding-review__feedback" aria-label="Agent feedback context">
        <ReviewFeedbackContext feedbackContext={feedbackContext} />

        {reviewsLink}

        <ReviewFeedbackForm form={form} setForm={setForm} saving={saving} error={error} canSave={canSave} onSave={saveFeedback} />
      </aside>
    </div>
  );
}
