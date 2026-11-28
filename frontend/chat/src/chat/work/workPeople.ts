import type { WorkItem } from "./workItemTypes";

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

// Filters match by id and only label the options with names.
export function assigneeFilterOptions(items: WorkItem[]): { values: string[]; labels: Record<string, string> } {
  const labels: Record<string, string> = {};
  for (const item of items) {
    const id = (item.assignee || "").trim();
    if (!id) continue;
    const label = personLabel(id, item.assignee_display);
    if (!labels[id] || labels[id] === id) labels[id] = label;
  }
  const values = Object.keys(labels).sort((left, right) => labels[left].localeCompare(labels[right]));
  return { values, labels };
}
