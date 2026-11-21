import { useCallback, useEffect, useState } from "react";

import { applyReviewerOverride, loadReviewerRecommendations } from "./workChangePlanApi";
import type { WorkItem } from "./workItemTypes";
import type { WorkReviewerCandidate, WorkReviewerRecommendationPayload } from "./workPullRequestTypes";
import { formatDateTime } from "./workUtils";
import { Badge } from "./WorkAreaViews";

// Reviewer suggestions: the touched repositories' declared default reviewers and owners (Settings →
// Workspace → Repositories), then the Workspace members. A name that is no member stays a named suggestion.
const MISSING_TEXT: Record<string, string> = {
  change_units: "Plan the change units first; reviewers follow the repositories they touch.",
  repository_owners: "No owner or default reviewer is declared for the touched repositories (Settings → Workspace → Repositories).",
};

const candidateKey = (candidate: WorkReviewerCandidate) => candidate.user_id || `name:${candidate.display_name}`;

export function WorkReviewerRecommendations({ item }: { item: WorkItem }) {
  const [payload, setPayload] = useState<WorkReviewerRecommendationPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setPayload(await loadReviewerRecommendations(item.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load reviewer recommendations");
    }
  }, [item.id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function selectReviewer(candidate: WorkReviewerCandidate) {
    setSavingKey(candidateKey(candidate));
    setError(null);
    try {
      await applyReviewerOverride({
        workItemId: item.id,
        selectedUserId: candidate.user_id ?? null,
        selectedReviewer: candidate.display_name,
        reason: "Selected from Work Item reviewer recommendations.",
        evidence: { score: candidate.score, evidence: candidate.evidence },
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save reviewer override");
    } finally {
      setSavingKey(null);
    }
  }

  if (error) return <p className="work-detail__empty">{error}</p>;
  if (!payload) return <p className="work-detail__empty">Loading reviewer recommendations…</p>;
  if (payload.missing_setup.length > 0) {
    return <p className="work-detail__empty">{payload.missing_setup.map((code) => MISSING_TEXT[code] ?? code).join(" ")}</p>;
  }
  return (
    <div className="work-reviewers">
      {payload.overrides.length > 0 ? (
        <div className="work-reviewers__overrides">
          <h4>Selected reviewers</h4>
          {payload.overrides.map((override) => (
            <div key={override.id}>
              <strong>{override.selected_reviewer}</strong>
              <span>{override.reason || "No reason captured."}</span>
              <span>{formatDateTime(override.created_at)}</span>
            </div>
          ))}
        </div>
      ) : null}
      <div className="work-reviewers__list">
        {payload.recommendations.slice(0, 5).map((candidate) => (
          <article key={candidateKey(candidate)} className="work-reviewer-card">
            <header>
              <div>
                <strong>{candidate.display_name}</strong>
                <span>{candidate.user_id ? candidate.primary_email || "Workspace member" : "Declared name, not a Workspace member"}</span>
              </div>
              <Badge value={`score ${candidate.score}`} />
            </header>
            <div className="work-reviewer-card__meta">
              {candidate.approval_roles.map((role) => <span key={role}>{role}</span>)}
              {candidate.scm_username ? <span>{candidate.scm_username}</span> : null}
            </div>
            <ul className="work-reviewer-card__evidence">
              {candidate.evidence.slice(0, 4).map((entry) => (
                <li key={`${candidateKey(candidate)}-${entry.kind}-${entry.reason}`}>
                  <span>{entry.points > 0 ? `+${entry.points}` : entry.points}</span>
                  {entry.reason}
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="work-area__button"
              onClick={() => void selectReviewer(candidate)}
              disabled={savingKey === candidateKey(candidate)}
            >
              {savingKey === candidateKey(candidate) ? "Selecting…" : "Select reviewer"}
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}
