import type { WorkItem } from "./workItemTypes";

// People on a Work Item by name. Pure: no React.
//
// The server keeps the Jira ids (`assignee`, `reporter`, `watchers`: Cloud accountId, Data Center name) and sends
// Jira's display name beside them (`assignee_display`, `reporter_display`, `watchers_display`). The UI shows the
// name and falls back to the id; filters keep matching by id and only label the options with names.

export function personLabel(id: string | null | undefined, display: string | null | undefined): string {
  const name = typeof display === "string" ? display.trim() : "";
  const key = typeof id === "string" ? id.trim() : "";
  return name || key;
}

export function assigneeLabel(item: WorkItem): string {
  return personLabel(item.assignee, item.assignee_display) || "Unassigned";
}

export function reporterLabel(item: WorkItem): string {
  return personLabel(item.reporter, item.reporter_display) || "-";
}

export function watcherLabels(item: WorkItem): string[] {
  const displays = new Map(
    (item.watchers_display || []).map((entry) => [entry?.id, entry?.display] as const),
  );
  return (item.watchers || []).map((id) => personLabel(id, displays.get(id)) || id);
}

/** The assignee filter: ids as values (sorted by their label), names as labels. */
export function assigneeFilterOptions(items: WorkItem[]): { values: string[]; labels: Record<string, string> } {
  const labels: Record<string, string> = {};
  for (const item of items) {
    const id = (item.assignee || "").trim();
    if (!id) continue;
    // A name sent for any of the id's items wins over the bare id.
    const label = personLabel(id, item.assignee_display);
    if (!labels[id] || labels[id] === id) labels[id] = label;
  }
  const values = Object.keys(labels).sort((left, right) => labels[left].localeCompare(labels[right]));
  return { values, labels };
}
