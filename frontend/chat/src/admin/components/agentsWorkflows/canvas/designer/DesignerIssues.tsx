// The designer's problem list: a summary line, expandable, each problem selecting its box or arrow.
import type { Dispatch, SetStateAction } from "react";

import type { DesignIssue } from "./issues";

export function DesignerIssues({ issues, issuesOpen, setIssuesOpen, dirty, onSelectEdge, onSelectNode }: {
  issues: DesignIssue[]; issuesOpen: boolean; setIssuesOpen: Dispatch<SetStateAction<boolean>>; dirty: boolean;
  onSelectEdge: (id: string) => void; onSelectNode: (id: string) => void;
}) {
  return (
    <section className={`dsg__issues${issuesOpen ? " is-open" : ""}`} data-testid="designer-validation" aria-label="Problems">
      <div className={`dsg__issues-head${issues.length ? " has-problems" : ""}`}>
        <span className="dsg__issues-dot" aria-hidden="true" />
        {issues.length ? `${issues.length === 1 ? "1 problem" : `${issues.length} problems`} to fix before publishing` : "No problems found"}
        {dirty ? <span className="admin-panel__hint">· not saved yet</span> : null}
        {issues.length > 2 ? (
          <button type="button" className="admin-panel__action-btn" aria-expanded={issuesOpen}
            onClick={() => setIssuesOpen((current) => !current)}>{issuesOpen ? "Show fewer" : `Show all ${issues.length}`}</button>
        ) : null}
      </div>
      {issues.length ? (
        <ul className="aw-issues">
          {issues.map((issue) => (
            <li key={issue.key}>
              <button type="button" className="admin-panel__action-btn" data-testid="designer-issue"
                {...(issue.nodeId ? { "data-node-id": issue.nodeId } : {})} {...(issue.edgeId ? { "data-edge-id": issue.edgeId } : {})}
                onClick={() => {
                  if (issue.edgeId) onSelectEdge(issue.edgeId);
                  else if (issue.nodeId) onSelectNode(issue.nodeId);
                }}>
                {issue.message}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
