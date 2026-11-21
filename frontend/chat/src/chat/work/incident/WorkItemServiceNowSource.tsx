import type { ProjectOption } from "../../../chatOptionTypes";
import { workspaceName } from "../workItemDetailModel";
import { formatDateTime } from "../workUtils";
import type { WorkItem } from "../workItemTypes";
import { KeyValue, PlainText, Section } from "../WorkItemJiraSource";
import { serviceNowSourceView } from "./workSourceModel";

// The ServiceNow side of a Work Item detail (D): the request text, the record's fields by name and the link to
// the record. Read-only: nothing here writes to ServiceNow.
export function WorkItemServiceNowSource({ item, projects, part = "all" }: {
  item: WorkItem; projects: ProjectOption[];
  // The request on the detail's Overview, the record's fields on its ServiceNow tab.
  part?: "all" | "request" | "fields";
}) {
  const view = serviceNowSourceView(item);
  return (
    <>
      {part !== "fields" ? (
        <Section title="Request">
          <PlainText text={item.description} empty="No ServiceNow description captured." testId="work-request-text" />
        </Section>
      ) : null}
      {part !== "request" ? (
      <Section title="ServiceNow Source">
        <div className="work-detail__kv-grid" data-testid="servicenow-source">
          <KeyValue label="Workspace" value={workspaceName(item.project_id, projects)} />
          <KeyValue label="Number" value={view.number} />
          <KeyValue label="Record type" value={view.table} />
          <KeyValue label="State" value={view.state} />
          <KeyValue label="Priority" value={view.priority} />
          <KeyValue label="Assignment group" value={view.assignmentGroup} />
          <KeyValue label="Assigned to" value={view.assignedTo} />
          <KeyValue label="Opened" value={view.openedAt ? formatDateTime(view.openedAt) : ""} />
        </div>
        {view.url ? (
          <a className="work-detail__source-link" href={view.url} target="_blank" rel="noopener noreferrer" data-testid="servicenow-link">
            Open in ServiceNow
          </a>
        ) : null}
      </Section>
      ) : null}
    </>
  );
}
