// The reads of the Coding page: the Workspace's sessions, one session's detail and the review verdicts. Review verdict
// reads are numbered when they start; see acceptRead for which read may write a verdict.
import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { loadCodingAuditReport } from "../work/workCodingApi";
import { loadCodingSessionDetail } from "./codingApi";
import type { CodingReviewSummary, CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import { buildCodingSessionSummary } from "./codingSessionModel";
import { latestByVersion } from "./codingSessionValues";
import { reviewSummaryFromAuditReport, reviewSummaryFromCandidate, unavailableReview } from "./codingReviewSummary";
import type { WorkCodingAuditReport } from "../work/workCodingReviewTypes";

export type SessionInputs = Parameters<typeof buildCodingSessionSummary>[0];
type Candidate = Awaited<ReturnType<typeof import("./codingApi").loadCodingWorkspaceData>>["sessionCandidates"][number];
export type ReviewAudit = { itemId: string; report: WorkCodingAuditReport | null } | null;

export type CodingReadRefs = {
  sessionInputs: MutableRefObject<Map<string, SessionInputs>>;
  reviewReads: MutableRefObject<number>;
  reviewFloors: MutableRefObject<Map<string, number>>;
  shownReviews: MutableRefObject<Map<string, CodingReviewSummary>>;
};

// Builds a session summary and remembers its inputs, so a new review verdict can rebuild it.
function summarizeInto(inputsById: Map<string, SessionInputs>, inputs: SessionInputs): CodingSessionSummary {
  inputsById.set(inputs.item.id, inputs);
  return buildCodingSessionSummary(inputs);
}

// Review verdict reads are numbered when they start. A read may write an item's verdict only if no
// later-started read has written it, and a recorded decision raises the floor at once, so every read
// that started before the decision is discarded.
function acceptRead(floors: Map<string, number>, itemId: string, started: number): boolean {
  if (started < (floors.get(itemId) ?? 0)) return false;
  floors.set(itemId, started);
  return true;
}

export function applyReview(
  refs: CodingReadRefs,
  setSessions: Dispatch<SetStateAction<CodingSessionSummary[]>>,
  itemId: string,
  review: CodingReviewSummary,
) {
  const { sessionInputs, shownReviews } = refs;
  shownReviews.current.set(itemId, review);
  const inputs = sessionInputs.current.get(itemId);
  if (!inputs) return;
  const next = summarizeInto(sessionInputs.current, { ...inputs, review });
  setSessions((current) => current.map((session) => (session.id === itemId ? next : session)));
}

  // After a recorded decision (or a retry): the previous verdict is invalid at once, then the audit
  // is re-read. A failure leaves the verdict explicitly unavailable, never the earlier value.
export async function refreshReviewOf(
  refs: CodingReadRefs,
  setSessions: Dispatch<SetStateAction<CodingSessionSummary[]>>,
  setReviewAudit: Dispatch<SetStateAction<ReviewAudit>>,
  itemId: string,
) {
  const { sessionInputs, reviewReads, reviewFloors } = refs;
  const applyReviewNow = (id: string, review: CodingReviewSummary) => applyReview(refs, setSessions, id, review);
  const started = ++reviewReads.current;
  reviewFloors.current.set(itemId, started);
  applyReviewNow(itemId, unavailableReview("refreshing"));
  setReviewAudit((current) => (current?.itemId === itemId ? { itemId, report: null } : current));
  try {
    const report = await loadCodingAuditReport(itemId);
    if (!acceptRead(reviewFloors.current, itemId, started)) return;
    const plans = sessionInputs.current.get(itemId)?.changePlans || [];
    applyReviewNow(itemId, reviewSummaryFromAuditReport(report, latestByVersion(plans)));
    setReviewAudit((current) => (current?.itemId === itemId ? { itemId, report } : current));
  } catch {
    if (!acceptRead(reviewFloors.current, itemId, started)) return;
    applyReviewNow(itemId, unavailableReview("refresh_failed"));
  }
}

// The session rows of a Workspace read.
export function sessionsFromCandidates(refs: CodingReadRefs, candidates: Candidate[], started: number) {
  const { sessionInputs, reviewFloors, shownReviews } = refs;
  return candidates
    .map((candidate) => {
      const id = candidate.work_item.id;
      // A read that started later (a detail load or a re-read after a decision) keeps its verdict.
      const review = acceptRead(reviewFloors.current, id, started)
        ? reviewSummaryFromCandidate(candidate.review_summary, latestByVersion(candidate.change_plans))
        : shownReviews.current.get(id) || unavailableReview("not_loaded");
      shownReviews.current.set(id, review);
      return summarizeInto(sessionInputs.current, {
        item: candidate.work_item,
        changePlans: candidate.change_plans,
        changeUnits: candidate.change_units,
        stateEvents: candidate.state_events,
        agentSessions: candidate.agent_sessions || [],
        pullRequestUrls: (candidate.pull_requests || []).map((pr) => pr.pr_url || "").filter(Boolean),
        review,
      });
    })
    .filter((session) => session.isCodingRelevant);
}

type DetailSetters = {
  setDetail: Dispatch<SetStateAction<CodingSessionDetailData | null>>;
  setDetailLoading: Dispatch<SetStateAction<boolean>>;
  setReviewAudit: Dispatch<SetStateAction<ReviewAudit>>;
  setSessions: Dispatch<SetStateAction<CodingSessionSummary[]>>;
  setError: Dispatch<SetStateAction<string | null>>;
};

function applyDetail(refs: CodingReadRefs, selectedId: string, started: number, nextDetail: CodingSessionDetailData, setters: DetailSetters) {
  const { sessionInputs, reviewFloors, shownReviews } = refs;
  const { setDetail, setReviewAudit, setSessions } = setters;
  setDetail(nextDetail);
  // The detail's own audit read is the verdict unless a newer review read started meanwhile;
  // a failed audit read is "unavailable", never the older list value.
  const current = acceptRead(reviewFloors.current, selectedId, started);
  if (current) setReviewAudit({ itemId: selectedId, report: nextDetail.auditReport });
  const review = current
    ? nextDetail.auditReport
      ? reviewSummaryFromAuditReport(nextDetail.auditReport, latestByVersion(nextDetail.changePlans))
      : unavailableReview("not_loaded")
    : shownReviews.current.get(selectedId) || unavailableReview("not_loaded");
  shownReviews.current.set(selectedId, review);
  setSessions((sessionsNow) =>
    sessionsNow.map((session) => {
      if (session.id !== selectedId) {
        return session;
      }
      return summarizeInto(sessionInputs.current, {
        item: nextDetail.workItem || session.workItem,
        changePlans: nextDetail.changePlans,
        changeUnits: nextDetail.changeUnits,
        stateEvents: nextDetail.stateEvents,
        agentSessions: session.agentSessions,
        pullRequestUrls: sessionInputs.current.get(selectedId)?.pullRequestUrls ?? [],
        review,
      });
    }),
  );
}

// Loads the selected session's detail; the returned cleanup drops a read that is no longer wanted.
export function loadSessionDetail(refs: CodingReadRefs, selectedId: string, setters: DetailSetters) {
  const { setDetail, setDetailLoading, setError } = setters;
  let cancelled = false;
  const started = ++refs.reviewReads.current;
  setDetailLoading(true);
  loadCodingSessionDetail(selectedId)
    .then((nextDetail) => {
      if (!cancelled) applyDetail(refs, selectedId, started, nextDetail, setters);
    })
    .catch((err) => {
      if (!cancelled) {
        // Not another session's evidence: the detail says it is not available and offers Try again.
        setDetail(null);
        setError(err instanceof Error ? err.message : "Failed to load Coding Session detail");
      }
    })
    .finally(() => { if (!cancelled) setDetailLoading(false); });
  return () => {
    cancelled = true;
  };
}
