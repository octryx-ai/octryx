import type { StatusTone } from "../../layout/StatusLabel";
import type { WorkItem } from "./workItemTypes";

// The lanes and their counts come from the backend (`/work-items/{id}/progress`); this module only shapes them for display.
export type EpicLane = "done" | "in_review" | "in_progress" | "open";
export type EpicChecks = "failed" | "green" | "running";
export type EpicProgressRow = {
  id: string;
  key: string;
  title: string;
  issueType: string;
  url: string;
  lane: EpicLane;
  reason: string;
  checks: EpicChecks | null;
  needsYou: boolean;
  runPhase: string;
  pullRequest: { url: string; status: string } | null;
};
export type EpicProgressStory = EpicProgressRow & { tasks: EpicProgressRow[]; tasksDone: number };
export type EpicProgressSummary = Record<EpicLane, number> & { total: number; needsYou: number };
export type EpicProgress = {
  epic: { id: string; key: string; title: string; url: string };
  summary: EpicProgressSummary;
  stories: EpicProgressStory[];
};
export type EpicBarSegment = { lane: EpicLane; label: string; count: number; share: number };

export const EPIC_LANES: EpicLane[] = ["done", "in_review", "in_progress", "open"];
const LANE_LABELS: Record<EpicLane, string> = { done: "Done", in_review: "In review", in_progress: "In progress", open: "Open" };
const LANE_TONES: Record<EpicLane, StatusTone> = { done: "success", in_review: "attention", in_progress: "info", open: "neutral" };
const CHECK_TONES: Record<EpicChecks, StatusTone> = { failed: "problem", green: "success", running: "info" };

export const laneLabel = (lane: EpicLane) => LANE_LABELS[lane];
export const laneTone = (lane: EpicLane) => LANE_TONES[lane];
export const checksTone = (checks: EpicChecks) => CHECK_TONES[checks];
export const checksLabel = (checks: EpicChecks) => `Checks ${checks}`;

export function epicProgressPath(epicId: string): string {
  return `/api/v1/secure-work/work-items/${encodeURIComponent(epicId)}/progress`;
}

export function reasonText(reason: string): string {
  const text = reason.replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

const text = (value: unknown) => (typeof value === "string" ? value : "");
const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : 0);
const record = (value: unknown) => (value && typeof value === "object" ? (value as Record<string, unknown>) : {});
const lane = (value: unknown): EpicLane => (EPIC_LANES.includes(value as EpicLane) ? (value as EpicLane) : "open");
const checks = (value: unknown): EpicChecks | null =>
  value === "failed" || value === "green" || value === "running" ? value : null;

function readRow(raw: unknown): EpicProgressRow {
  const row = record(raw);
  const pr = row.pull_request ? record(row.pull_request) : null;
  return {
    id: text(row.id), key: text(row.key), title: text(row.title) || text(row.key), issueType: text(row.issue_type),
    url: text(row.url), lane: lane(row.lane), reason: text(row.reason), checks: checks(row.checks),
    needsYou: row.needs_you === true, runPhase: row.run ? text(record(row.run).phase) : "",
    pullRequest: pr ? { url: text(pr.url), status: text(pr.status) } : null,
  };
}

// Needs-you first, then in review, in progress, open, and done last: what still moves is on top.
const SORT_ORDER: EpicLane[] = ["in_review", "in_progress", "open", "done"];
const sortRank = (row: EpicProgressRow) => (row.needsYou ? -1 : SORT_ORDER.indexOf(row.lane));
const byLane = (left: EpicProgressRow, right: EpicProgressRow) =>
  sortRank(left) - sortRank(right) || compareKeys(left.key, right.key);

export function readEpicProgress(raw: unknown): EpicProgress {
  const payload = record(raw);
  const epic = record(payload.epic);
  const summary = record(payload.summary);
  const stories = (Array.isArray(payload.stories) ? payload.stories : []).map((entry) => {
    const tasks = (Array.isArray(record(entry).tasks) ? (record(entry).tasks as unknown[]) : []).map(readRow);
    return { ...readRow(entry), tasks: tasks.sort(byLane), tasksDone: num(record(entry).tasks_done) };
  });
  return {
    epic: { id: text(epic.id), key: text(epic.key), title: text(epic.title) || text(epic.key), url: text(epic.url) },
    summary: {
      done: num(summary.done), in_review: num(summary.in_review), in_progress: num(summary.in_progress),
      open: num(summary.open), total: num(summary.total), needsYou: num(summary.needs_you),
    },
    stories: stories.sort(byLane),
  };
}

export function barSegments(summary: EpicProgressSummary): EpicBarSegment[] {
  const total = summary.total || EPIC_LANES.reduce((sum, key) => sum + summary[key], 0);
  return EPIC_LANES.map((key) => ({
    lane: key, label: LANE_LABELS[key], count: summary[key],
    share: total ? Math.round((summary[key] / total) * 1000) / 10 : 0,
  }));
}

export function needsYouText(summary: EpicProgressSummary): string {
  return summary.needsYou ? `${summary.needsYou} ${plural(summary.needsYou, "needs", "need")} you` : "";
}

export function tasksDoneText(story: EpicProgressStory): string {
  return story.tasks.length ? `${story.tasksDone}/${story.tasks.length} tasks done` : "";
}

export function isEpic(item: Pick<WorkItem, "issue_type">): boolean {
  return String(item.issue_type || "").trim().toLowerCase() === "epic";
}

export function compareKeys(left: string, right: string): number {
  return String(left || "").localeCompare(String(right || ""), undefined, { numeric: true, sensitivity: "base" });
}

export function epicsOf(items: WorkItem[]): WorkItem[] {
  return items.filter(isEpic);
}

export function chooseEpic(epics: WorkItem[], wanted: string | null | undefined): WorkItem | null {
  return epics.find((epic) => epic.source_key === wanted) ?? epics[0] ?? null;
}

export const plural = (value: number, word: string, many = `${word}s`) => (value === 1 ? word : many);
