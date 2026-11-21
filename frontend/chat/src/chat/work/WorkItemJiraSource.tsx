import type { ReactNode } from "react";

import type { ProjectOption } from "../../chatOptionTypes";
import { formatDateTime } from "./workUtils";
import {
  boardText,
  commentsView,
  safeHttpUrl,
  sprintGoal,
  sprintText,
  statusMappingText,
  textBlocks,
  workspaceName,
} from "./workItemDetailModel";
import { personLabel, reporterLabel, assigneeLabel, watcherLabels } from "./workPeople";
import { JiraWikiText } from "./JiraWikiText";
import type { WorkItem } from "./workItemTypes";

// The Jira side of a Work Item detail: the request and comments rendered from Jira's wiki markup
// (JiraWikiText, never HTML), the Jira fields with people by name, sprint and board by name and the Workspace by name, and the synced
// Jira comments (read-only). Same section markup as the rest of the detail.
export function WorkItemJiraSource({
  item,
  projects,
  acceptanceCriteria,
  part = "all",
}: {
  item: WorkItem;
  projects: ProjectOption[];
  acceptanceCriteria: string;
  // The detail shows the request on Overview and the Jira fields and comments on its Jira tab.
  part?: "all" | "request" | "fields";
}) {
  const mapping = statusMappingText(item);
  const goal = sprintGoal(item.sprint);
  const sourceUrl = safeHttpUrl(item.source_url);
  return (
    <>
      {part !== "fields" ? (
        <Section title="Request">
          <JiraWikiText text={item.description} empty="No Jira description captured." testId="work-request-text" />
          {/* Shown only when there are criteria: a lone "-" under the request is noise. */}
          {acceptanceCriteria.trim() && acceptanceCriteria.trim() !== "-" ? <KeyValue label="Acceptance criteria" value={acceptanceCriteria} /> : null}
        </Section>
      ) : null}

      {part !== "request" ? (<>
      <Section title="Jira Source">
        <div className="work-detail__kv-grid">
          <KeyValue label="Workspace" value={workspaceName(item.project_id, projects)} />
          <KeyValue label="Project" value={item.source_project_key} />
          <KeyValue label="Status" value={item.source_status} />
          <KeyValue label="Issue type" value={item.issue_type} />
          <KeyValue label="Priority" value={item.priority} />
          <KeyValue label="Assignee" value={assigneeLabel(item)} />
          <KeyValue label="Reporter" value={reporterLabel(item)} />
          <KeyValue label="Watchers" value={watcherLabels(item).join(", ")} />
          <KeyValue label="Fix version" value={(item.fix_versions || []).join(", ")} />
          <KeyValue label="Components" value={(item.components || []).join(", ")} />
          <KeyValue label="Labels" value={(item.labels || []).join(", ")} />
          <KeyValue label="Sprint" value={goal ? `${sprintText(item.sprint)} · goal: ${goal}` : sprintText(item.sprint)} />
          <KeyValue label="Board" value={boardText(item.board)} />
          <KeyValue label="Parent" value={item.parent_key} />
          <KeyValue label="Epic" value={item.epic_key} />
          <KeyValue label="Created" value={formatDateTime(item.source_created_at)} />
          <KeyValue label="Updated" value={formatDateTime(item.last_source_updated_at)} />
        </div>
        {mapping ? (
          <p className="work-detail__empty" data-testid="work-status-mapping">
            Work state {item.work_state.replace(/_/g, " ")}: {mapping}.
          </p>
        ) : null}
        {sourceUrl ? (
          <a className="work-detail__source-link" href={sourceUrl} target="_blank" rel="noopener noreferrer">
            Open Jira source
          </a>
        ) : null}
      </Section>

      <Section title="Jira Comments">
        <Comments item={item} />
      </Section>
      </>) : null}
    </>
  );
}

function Comments({ item }: { item: WorkItem }) {
  const view = commentsView(item);
  if (view.state === "not_reported") {
    return <p className="work-detail__empty">This server does not sync Jira comments yet.</p>;
  }
  if (!view.comments.length) return <p className="work-detail__empty">No comments in Jira.</p>;
  return (
    <>
      {view.older ? (
        <p className="work-detail__empty">
          Showing the last {view.comments.length} comments; {view.older} older {view.older === 1 ? "one is" : "ones are"} only in Jira.
        </p>
      ) : null}
      <ul className="work-detail__object-list" data-testid="work-comments">
        {view.comments.map((comment) => {
          const link = safeHttpUrl(comment.url);
          return (
            <li key={comment.id}>
              <strong>{personLabel(comment.author, comment.author_display) || "Unknown author"}</strong>
              {" · "}
              {formatDateTime(comment.created)}
              {link ? <>{" · "}<a href={link} target="_blank" rel="noopener noreferrer">Open in Jira</a></> : null}
              <JiraWikiText text={comment.body} empty="(empty comment)" />
            </li>
          );
        })}
      </ul>
    </>
  );
}

export function PlainText({ text, empty, testId }: { text: string | null | undefined; empty: string; testId?: string }) {
  const blocks = textBlocks(text);
  if (!blocks.length) return <p data-testid={testId}>{empty}</p>;
  return (
    <div className="work-detail__stack" data-testid={testId}>
      {blocks.map((block, index) =>
        block.kind === "list" ? (
          <ul key={index}>{block.items.map((entry, itemIndex) => <li key={itemIndex}>{entry}</li>)}</ul>
        ) : (
          <p key={index}>
            {block.lines.map((line, lineIndex) => (
              <span key={lineIndex}>
                {lineIndex ? <br /> : null}
                {line}
              </span>
            ))}
          </p>
        ),
      )}
    </div>
  );
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="work-detail__section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

export function KeyValue({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="work-detail__kv">
      <dt>{label}</dt>
      <dd>{value && value.trim() ? value : "-"}</dd>
    </div>
  );
}
