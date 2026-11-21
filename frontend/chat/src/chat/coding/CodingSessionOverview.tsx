import type { CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import { latestByVersion } from "./codingSessionValues";
import { RuntimeObservabilitySummary } from "./CodingRuntimeObservability";
import { blockerCountText, reviewSummaryLabel } from "./codingReviewSummary";
import { validationLabel } from "./codingEvidenceModel";
import { CodingContextBudgetEvidence } from "./CodingProcessEvidence";
import { sessionEnded } from "./codingSessionSteps";
import { TimeText } from "../../admin/utils/TimeText";
import { CompactJson, ExternalEvidenceLink, ExternalLinkList, KeyValue } from "./codingDetailParts";
import {
  branchLinkEntries,
  compactUrlLabel,
  contextBudgetRecord,
  phaseLabel,
  repositoryLinkEntries,
  sprintLabel,
} from "./codingDetailValues";

// What the session does next, in one sentence, with the work review verdict and its Retry. It stays above
// the steps, so a person sees the next step without opening anything; the counters live in Details.
// An ended session shows its outcome instead: no current action, and no work review line without a plan to review.
export function CodingSessionCockpit({ session, onRetryReview }: { session: CodingSessionSummary; onRetryReview?: () => void }) {
  const retryable = session.review.status === "unavailable" && session.review.cause !== "refreshing";
  const ended = sessionEnded(session);
  const reviewLine = !ended || Boolean(session.latestPlanStatus);
  return (
    <section className="coding-cockpit">
      <div className="coding-cockpit__primary">
        <div className="work-area__eyebrow">{ended ? "Outcome" : "Current action"}</div>
        <h3>{session.nextAction}</h3>
        {/* The work review verdict as one full-width line; the side keeps the quantitative metrics. */}
        {reviewLine ? (
          <p role={retryable ? "status" : undefined}>
            {reviewSummaryLabel(session.review)}
            {retryable && onRetryReview ? (
              <>
                {" "}
                <button type="button" className="work-area__button" onClick={onRetryReview}>Retry</button>
              </>
            ) : null}
          </p>
        ) : null}
      </div>
    </section>
  );
}

// The session's counters.
export function CodingSessionCounters({ session }: { session: CodingSessionSummary }) {
  return (
    <div className="coding-detail__counters" aria-label="Session counters">
      <KeyValue label="Phase" value={phaseLabel(session.phase)} />
      <KeyValue label="Blockers" value={blockerCountText(session.blockerCount, session.review, false)} />
      <KeyValue label="Recorded evidence" value={String(session.recordedEvidenceCount)} />
      <KeyValue label="Repository" value={session.repositories[0] || "Not planned yet"} />
      <KeyValue label="Pull requests" value={String(session.pullRequests.length)} />
      <KeyValue label="Validation" value={validationLabel(session.validation)} />
      <KeyValue label="Work review" value={reviewSummaryLabel(session.review)} />
    </div>
  );
}

// The session's facts for its Details section: the runtime record,
// the prompt budget and the work item's fields. The steps above carry the progress.
export function CodingSessionFacts({
  session,
  sourceFields,
  detail,
  latestPlan,
}: {
  session: CodingSessionSummary;
  sourceFields: Record<string, unknown> | null;
  detail: CodingSessionDetailData | null;
  latestPlan: ReturnType<typeof latestByVersion>;
}) {
  const repositoryLinks = repositoryLinkEntries(session, latestPlan);
  const branchLinks = branchLinkEntries(session, detail, latestPlan);
  const pullRequestLinks = session.pullRequests.map((url) => ({ label: compactUrlLabel(url), href: url }));
  const contextBudget = contextBudgetRecord(detail);
  return (
    <div className="coding-detail__stack">
      <CodingSessionCounters session={session} />
      <KeyValue label="Description" value={session.workItem.description || "No description imported from the source task."} />
      {contextBudget ? (
        <KeyValue label="Prompt budget" value={`${String(contextBudget.estimated_prompt_tokens ?? "-")} est. tokens`} />
      ) : null}
      <RuntimeObservabilitySummary observability={detail?.observability || null} />
      {contextBudget ? <CodingContextBudgetEvidence budget={contextBudget} /> : null}
      <div className="coding-detail__grid">
        <KeyValue
          label="Work Item"
          value={<ExternalEvidenceLink href={session.workItem.source_url} label={session.sourceKey} />}
        />
        <KeyValue label="Jira status" value={session.workItem.source_status || "-"} />
        <KeyValue label="Work state" value={session.workItem.work_state || "-"} />
        <KeyValue label="Assignee" value={session.workItem.assignee || "Unassigned"} />
        <KeyValue label="Repositories" value={<ExternalLinkList links={repositoryLinks} emptyText="Not planned" />} />
        <KeyValue label="Planned branches" value={<ExternalLinkList links={branchLinks} emptyText="Not planned" />} />
        <KeyValue label="Pull requests" value={<ExternalLinkList links={pullRequestLinks} emptyText="No PR linked" />} />
        <KeyValue label="Last update" value={<TimeText value={session.updatedAt} fallback="-" />} />
        <KeyValue label="Release" value={(session.workItem.fix_versions || []).join(", ") || "-"} />
        <KeyValue label="Sprint" value={sprintLabel(session.workItem.sprint)} />
        <KeyValue label="Labels" value={(session.workItem.labels || []).join(", ") || "-"} />
      </div>
      <div className="coding-detail__wide">
        <h3>Task evidence</h3>
        <CompactJson
          value={{
            acceptance_criteria: sourceFields?.acceptance_criteria,
            source_url: session.workItem.source_url,
            automation: session.workItem.automation_eligibility,
          }}
        />
      </div>
    </div>
  );
}
