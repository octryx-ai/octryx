import { safeHttpUrl } from "../workItemDetailModel";
import type { WorkItem } from "../workItemTypes";

// Where a Work Item comes from: Jira or ServiceNow (`source_type`). Pure: no React.
// ServiceNow items carry `source_key` = the record number, `source_url` = the record link, `source_status` = the
// ServiceNow state, and the record's other fields in `source_fields` (assignment group, assigned to, opened at, table).

export const SOURCE_SERVICENOW = "servicenow";
export const SOURCE_JIRA = "jira";

const SOURCE_LABEL: Record<string, string> = { servicenow: "ServiceNow", jira: "Jira" };

/** The system's name for a `source_type`; an unknown one keeps its value; an empty one reads as Jira (older items). */
export function sourceLabel(sourceType: string | null | undefined): string {
  const value = String(sourceType || "").trim().toLowerCase();
  if (!value) return SOURCE_LABEL.jira;
  return SOURCE_LABEL[value] ?? value;
}

export function isServiceNowItem(item: Pick<WorkItem, "source_type">): boolean {
  return String(item.source_type || "").trim().toLowerCase() === SOURCE_SERVICENOW;
}

/** The source filter's options: every source present, as `{value: label}` (empty source_type counts as Jira). */
export function sourceFilterOptions(items: Pick<WorkItem, "source_type">[]): { values: string[]; labels: Record<string, string> } {
  const values = Array.from(new Set(items.map((item) => String(item.source_type || "").trim().toLowerCase() || SOURCE_JIRA))).sort();
  return { values, labels: Object.fromEntries(values.map((value) => [value, sourceLabel(value)])) };
}

export function sourceMatches(item: Pick<WorkItem, "source_type">, sourceType: string): boolean {
  if (!sourceType) return true;
  return (String(item.source_type || "").trim().toLowerCase() || SOURCE_JIRA) === sourceType;
}

const text = (value: unknown): string => {
  if (typeof value === "string") return value.trim();
  // ServiceNow display values may come as {display_value, value}.
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return text(record.display_value ?? record.name ?? record.value);
  }
  return "";
};

const TABLE_LABEL: Record<string, string> = { incident: "Incident", change_request: "Change request" };

export type ServiceNowSourceView = {
  number: string;
  table: string;
  state: string;
  priority: string;
  assignmentGroup: string;
  assignedTo: string;
  openedAt: string | null;
  url: string | null;
};

/** The ServiceNow fields of an item, read from the item and its `source_fields`; never a raw object. */
export function serviceNowSourceView(item: WorkItem): ServiceNowSourceView {
  const fields = (item.source_fields || {}) as Record<string, unknown>;
  const table = text(fields.table) || text(fields.sys_class_name);
  return {
    number: item.source_key,
    table: TABLE_LABEL[table] ?? table,
    state: text(item.source_status) || text(fields.state),
    priority: text(item.priority) || text(fields.priority),
    assignmentGroup: text(fields.assignment_group),
    assignedTo: text(fields.assigned_to) || text(item.assignee_display) || text(item.assignee),
    openedAt: text(fields.opened_at) || text(item.source_created_at) || null,
    url: safeHttpUrl(item.source_url),
  };
}
