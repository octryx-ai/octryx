import { useCallback, useEffect, useRef, useState } from "react";

import { loadCodingReviewEvents } from "../work/workCodingApi";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkChangeUnit, WorkReviewerRecommendationPayload } from "../work/workPullRequestTypes";
import type { WorkCodingReviewEvent, WorkCodingReviewEventsPayload } from "../work/workCodingReviewTypes";
import { CodingReviewDecisionPanel } from "./CodingReviewDecisionPanel";

type LoadReviewEvents = (workItemId: string) => Promise<WorkCodingReviewEventsPayload>;

// The Reviews tab: the one place to record a work-review decision (Approve / Request changes
// / Reject), followed by reviewer recommendations and overrides. Review events are loaded here, for
// this Work Item, with their own loading, error and refresh state.
export function CodingReviewsPanel({
  workItemId,
  latestPlan,
  changeUnits,
  reviewerPayload,
  fallbackRecommendations = [],
  load = loadCodingReviewEvents,
  onRecorded,
}: {
  workItemId: string;
  latestPlan: WorkChangePlan | null;
  changeUnits: WorkChangeUnit[];
  reviewerPayload: WorkReviewerRecommendationPayload | null;
  fallbackRecommendations?: unknown[];
  load?: LoadReviewEvents;
  // A saved decision changes the reviewer verdict; the parent re-reads it.
  onRecorded?: (created: WorkCodingReviewEvent) => void;
}) {
  const [events, setEvents] = useState<WorkCodingReviewEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);

  const refresh = useCallback(async () => {
    const current = ++request.current;
    setLoading(true);
    setError(null);
    try {
      const payload = await load(workItemId);
      if (current === request.current) setEvents(payload.items || []);
    } catch (caught) {
      if (current === request.current) {
        const message = caught && typeof caught === "object" && "message" in caught ? (caught as { message?: unknown }).message : null;
        setError(typeof message === "string" && message ? message : "Review decisions could not be loaded.");
      }
    } finally {
      if (current === request.current) setLoading(false);
    }
  }, [workItemId, load]);

  useEffect(() => {
    setEvents([]);
    void refresh();
    return () => {
      // A later item or an unmount makes this load stale.
      request.current += 1;
    };
  }, [refresh]);

  const recommendations = reviewerPayload?.recommendations || fallbackRecommendations;
  const overrides = reviewerPayload?.overrides || [];
  const missingSetup = reviewerPayload?.missing_setup || [];

  return (
    <div className="coding-detail__stack" aria-label="Reviews">
      <section className="coding-detail__evidence">
        {/* Only the decision here; what a work review is (and is not) lives in help/coding/sessions.md. */}
        <h3>Work review</h3>
        {error ? (
          <p className="coding-detail__warning" role="alert">
            {error}{" "}
            <button type="button" className="work-area__button" onClick={() => void refresh()}>Retry</button>
          </p>
        ) : null}
        {loading ? <p className="work-detail__empty">Loading review decisions…</p> : null}
      </section>
      {!loading && !error ? (
        <CodingReviewDecisionPanel
          workItemId={workItemId}
          latestPlan={latestPlan}
          changeUnits={changeUnits}
          events={events}
          onRecorded={(created) => {
            setEvents((current) => [...current, created]);
            onRecorded?.(created);
          }}
        />
      ) : null}
      {missingSetup.length > 0 ? (
        <p className="coding-detail__warning">Missing reviewer setup: {missingSetup.join(", ")}</p>
      ) : null}
      <section className="coding-detail__evidence">
        <h3>Reviewer recommendations</h3>
        {recommendations.length === 0 ? <p className="work-detail__empty">No reviewer recommendation captured yet.</p> : (
          <ul>
            {recommendations.map((entry, index) => (
              <li key={`recommendation-${index}`}>{reviewerLine(entry)}</li>
            ))}
          </ul>
        )}
      </section>
      <section className="coding-detail__evidence">
        <h3>Reviewer overrides</h3>
        <p className="work-detail__empty">An override records who should review; it is not an approval.</p>
        {overrides.length === 0 ? <p className="work-detail__empty">No reviewer override recorded.</p> : (
          <ul>
            {overrides.map((entry, index) => (
              <li key={`override-${index}`}>{reviewerLine(entry)}</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function reviewerLine(entry: unknown): string {
  if (typeof entry === "string") return entry;
  const fields = entry && typeof entry === "object" && !Array.isArray(entry) ? (entry as Record<string, unknown>) : {};
  const name = [fields.display_name, fields.selected_reviewer, fields.name].find((value) => typeof value === "string" && value);
  const detail = [fields.reason, fields.rationale].find((value) => typeof value === "string" && value);
  const score = typeof fields.score === "number" ? ` · score ${fields.score}` : "";
  return `${typeof name === "string" ? name : "Reviewer"}${score}${typeof detail === "string" ? ` · ${detail}` : ""}`;
}
