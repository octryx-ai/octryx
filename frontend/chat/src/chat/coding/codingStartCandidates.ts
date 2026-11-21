import type { WorkItem } from "../work/workItemTypes";

// Pure helpers for the coding session start dialog.
export const START_DIALOG_COPY = {
  title: "Start coding session",
  intro:
    "A coding session starts with a change plan: choose the work item, describe the request and name the repositories " +
    "to change. The plan is created for review; the coding agent starts once the plan is approved.",
  submit: "Create change plan and start",
  submitting: "Creating change plan...",
  noItems: "No work items available — import them in Work → Intake.",
  noMatches: "No work items match the search.",
};

export const START_CANDIDATE_LIMIT = 80;

export function sortStartCandidates(items: WorkItem[]): WorkItem[] {
  return [...items].sort((left, right) => {
    const leftScore = startCandidateScore(left);
    const rightScore = startCandidateScore(right);
    if (leftScore !== rightScore) {
      return rightScore - leftScore;
    }
    return timestamp(right) - timestamp(left);
  });
}

export function filterStartCandidates(items: WorkItem[], search: string): WorkItem[] {
  const needle = search.trim().toLowerCase();
  if (!needle) {
    return items.slice(0, START_CANDIDATE_LIMIT);
  }
  return items
    .filter((item) =>
      [
        item.source_key,
        item.title,
        item.assignee || "",
        item.source_status || "",
        ...(item.labels || []),
        ...(item.fix_versions || []),
      ]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    )
    .slice(0, START_CANDIDATE_LIMIT);
}

export function startListMessage(totalItems: number, visibleItems: number): string | null {
  if (totalItems === 0) return START_DIALOG_COPY.noItems;
  if (visibleItems === 0) return START_DIALOG_COPY.noMatches;
  return null;
}

// Appends a known repository name to the one-per-line repository field.
export function appendRepository(text: string, name: string): string {
  const entries = splitLines(text);
  return entries.includes(name) ? text : [...entries, name].join("\n");
}

export function splitLines(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export function defaultIntent(item: WorkItem): string {
  return `${item.source_key}: ${item.title}${item.description ? `\n\n${item.description}` : ""}`;
}

function startCandidateScore(item: WorkItem): number {
  let score = 0;
  if (item.automation_eligibility?.requested) {
    score += 100;
  }
  if (!["done", "completed", "cancelled"].includes(item.work_state)) {
    score += 10;
  }
  if (item.source_status && !["closed", "resolved", "verified"].includes(item.source_status.toLowerCase())) {
    score += 5;
  }
  return score;
}

function timestamp(item: WorkItem): number {
  return Date.parse(item.last_source_updated_at || item.updated_at || item.synced_at || "") || 0;
}
