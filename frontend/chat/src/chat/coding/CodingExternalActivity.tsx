import type { CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import { recordValue } from "./codingSessionValues";
import { CompactJson, EvidenceList } from "./codingDetailParts";
import { arrayValue, stringValue } from "./codingDetailValues";

// External activity of a session (Jira, watcher events, CI/CD findings, PR data), shown in its Details.
export function CodingExternalActivity({
  sourceFields,
  session,
  detail,
}: {
  sourceFields: Record<string, unknown> | null;
  session: CodingSessionSummary;
  detail: CodingSessionDetailData | null;
}) {
  const externalActivity = arrayValue(sourceFields?.external_activity);
  return (
    <div className="coding-detail__stack">
      <EvidenceList title="Jira" values={[session.workItem.source_url || session.sourceKey]} />
      <ExternalActivityList values={externalActivity} sessionId={session.id} />
      <CicdFindingsList findings={detail?.cicdFindings?.items || []} />
      <EvidenceList
        title="Pull requests"
        values={sourceFields?.pull_requests || session.pullRequests}
        emptyText="No external PR data captured yet."
      />
      <EvidenceList
        title="Execution runs"
        values={sourceFields?.execution_runs || []}
        emptyText="No agent execution run linked yet."
      />
    </div>
  );
}

export function ExternalActivityList({ values, sessionId }: { values: unknown[]; sessionId: string }) {
  return (
    <section className="coding-detail__evidence">
      <h3>External activity</h3>
      {values.length === 0 ? (
        <p className="work-detail__empty">No external watcher event linked yet.</p>
      ) : null}
      {values.length > 0 ? (
        <ul>
          {values.map((value, index) => {
            const activity = recordValue(value) || {};
            const repository = recordValue(activity.repository) || {};
            const pullRequest = recordValue(activity.pull_request) || {};
            const commit = recordValue(activity.commit) || {};
            const comment = recordValue(activity.comment) || {};
            const reviewer = recordValue(activity.reviewer) || {};
            const issue = recordValue(activity.issue) || {};
            const page = recordValue(activity.page) || {};
            const document = recordValue(activity.document) || {};
            const ruleDecisions = arrayValue(activity.rule_decisions);
            const resultingActions = arrayValue(activity.resulting_actions);
            const title = [
              stringValue(activity.event_type),
              stringValue(repository.slug) || stringValue(repository.name),
              stringValue(issue.key),
              stringValue(page.title) || stringValue(page.id),
              stringValue(document.key) || stringValue(document.title),
              stringValue(activity.branch),
            ].filter(Boolean).join(" · ");
            return (
              <li key={`${activity.event_id || "bitbucket"}-${index}`}>
                <div className="coding-detail__finding">
                  <div>
                    <strong>{title || "Bitbucket event"}</strong>
                    <small>
                      {[
                        stringValue(activity.source),
                        stringValue(activity.actor),
                        stringValue(activity.received_at),
                        pullRequest.id ? `PR ${String(pullRequest.id)}` : "",
                      ].filter(Boolean).join(" · ")}
                    </small>
                  </div>
                  <span className={`work-badge work-badge--${activity.requires_replan ? "attention" : "neutral"}`}>
                    {activity.requires_replan ? "replan" : "linked"}
                  </span>
                </div>
                {comment.text ? <p>{String(comment.text)}</p> : null}
                {reviewer.display_name || reviewer.name ? (
                  <p>Reviewer: {String(reviewer.display_name || reviewer.name)}</p>
                ) : null}
                {commit.hash ? <p>Commit: {String(commit.hash)}</p> : null}
                {issue.key ? <p>Issue: {String(issue.key)}</p> : null}
                {page.title || page.id ? <p>Page: {String(page.title || page.id)}</p> : null}
                {document.key ? <p>Knowledge: {String(document.key)}</p> : null}
                <p>Linked session: {String(activity.event_id || sessionId)}</p>
                {resultingActions.length > 0 ? (
                  <p>Actions: {resultingActions.map((entry) => stringValue(entry)).filter(Boolean).join(", ")}</p>
                ) : null}
                <CompactJson
                  value={{
                    matched_by: activity.matched_by,
                    force_push: activity.force_push,
                    source_evidence_stale: activity.source_evidence_stale,
                    rule_decisions: ruleDecisions,
                    pull_request: pullRequest,
                  }}
                />
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}

export function CicdFindingsList({
  findings,
}: {
  findings: NonNullable<CodingSessionDetailData["cicdFindings"]>["items"];
}) {
  return (
    <section className="coding-detail__evidence">
      <h3>CI/CD findings</h3>
      {findings.length === 0 ? <p className="work-detail__empty">No CI/CD finding captured yet.</p> : null}
      {findings.length > 0 ? (
        <ul>
          {findings.map((finding) => (
            <li key={finding.id}>
              <div className="coding-detail__finding">
                <div>
                  <strong>{finding.title}</strong>
                  <small>
                    {[
                      finding.job_name,
                      finding.build_number ? `#${finding.build_number}` : "",
                      finding.commit_sha ? `commit ${finding.commit_sha}` : "",
                    ].filter(Boolean).join(" · ")}
                  </small>
                </div>
                <span className={`work-badge work-badge--${finding.status === "stale_ignored" ? "neutral" : finding.event_status === "failed" ? "danger" : "neutral"}`}>
                  {finding.status === "stale_ignored" ? "stale" : finding.event_status}
                </span>
              </div>
              {finding.summary ? <p>{finding.summary}</p> : null}
              {finding.stale_reason ? <p className="coding-detail__warning">{finding.stale_reason}</p> : null}
              {finding.build_url ? (
                <a href={finding.build_url} target="_blank" rel="noreferrer">
                  Open CI/CD run
                </a>
              ) : null}
              {finding.artifacts.length > 0 || finding.comments.length > 0 ? (
                <CompactJson value={{ artifacts: finding.artifacts, comments: finding.comments }} />
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
