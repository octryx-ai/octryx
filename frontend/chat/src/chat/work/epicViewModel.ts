// Work › Epics (the agreed mock "Work: epic, stories, tasks"): one epic, its stories (work items whose
// `epic_key` is the epic's key; one story = one branch, one pull request), each with its tasks, status, pull request and
// model cost. Composed from existing reads: the Work item list (lean rows with `epic_key`, `issue_type`), the item
// detail per story (`task_list`) and GET /api/v1/workflow-runs?view=work (pull_request, cost, status per run).

import type { StatusTone } from "../../layout/StatusLabel";
import type { SeatFigures } from "../cost/seatEquivalent";
import type { RunTaskItem } from "../workflowRun/workflowRunTypes";
import { taskStatus } from "../workflowRun/taskListModel";
import { hasPullRequest, needsPerson, totalSeat, type WorkRunRow } from "./workRunsModel";
import type { WorkItem } from "./workItemTypes";

export type EpicRun = WorkRunRow & { work_item_id?: string | null };
export type EpicStory = { item: WorkItem; tasks: RunTaskItem[]; runs: EpicRun[] };
export type StoryStatus = { label: string; tone: StatusTone };

const DONE_STATES = new Set(["done", "closed", "resolved"]);

export function isEpic(item: Pick<WorkItem, "issue_type">): boolean {
  return String(item.issue_type || "").trim().toLowerCase() === "epic";
}

/** "" sorts after "": the key's text, then its number. */
export function compareKeys(left: string, right: string): number {
  return String(left || "").localeCompare(String(right || ""), undefined, { numeric: true, sensitivity: "base" });
}

/** The epics in the list, in the list's order (most recently changed first). */
export function epicsOf(items: WorkItem[]): WorkItem[] {
  return items.filter(isEpic);
}

/** The epic to show: the one the address names, else the first. */
export function chooseEpic(epics: WorkItem[], wanted: string | null | undefined): WorkItem | null {
  return epics.find((epic) => epic.source_key === wanted) ?? epics[0] ?? null;
}

/** The epic's stories (work items with its key in `epic_key`), by key. */
export function storiesOf(items: WorkItem[], epicKey: string): WorkItem[] {
  if (!epicKey) return [];
  return items.filter((item) => item.epic_key === epicKey && !isEpic(item))
    .sort((left, right) => compareKeys(left.source_key, right.source_key));
}

/** Runs per work item id, newest first (the list comes newest first). */
export function runsByItem(runs: EpicRun[]): Map<string, EpicRun[]> {
  const byItem = new Map<string, EpicRun[]>();
  for (const run of runs) {
    if (!run.work_item_id) continue;
    byItem.set(run.work_item_id, [...(byItem.get(run.work_item_id) ?? []), run]);
  }
  return byItem;
}

const count = (tasks: RunTaskItem[], wanted: string[]) => tasks.filter((task) => wanted.includes(taskStatus(task))).length;

/** The bar under a story: the share of done (✓ or ✓✓) and of tasks with requested changes, in percent. */
export function progressShares(tasks: RunTaskItem[]): { done: number; changes: number } {
  if (!tasks.length) return { done: 0, changes: 0 };
  const share = (value: number) => Math.round((value / tasks.length) * 100);
  return { done: share(count(tasks, ["done", "verified"])), changes: share(count(tasks, ["changes"])) };
}

const isShipped = (story: EpicStory) => DONE_STATES.has(String(story.item.work_state || "").toLowerCase())
  || (story.runs[0]?.status === "completed" && hasPullRequest(story.runs[0]?.pull_request));

/** One word for the story: what waits for a person first, then what is running, then how its newest run ended. */
export function storyStatus(story: EpicStory): StoryStatus {
  const { runs, tasks } = story;
  if (runs.some(needsPerson)) return { label: "Needs you", tone: "attention" };
  if (runs.some((run) => run.status === "running")) return { label: "Building", tone: "info" };
  if (isShipped(story)) return { label: "Shipped", tone: "success" };
  const latest = runs[0];
  if (latest?.status === "failed") return { label: "Failed", tone: "problem" };
  if (latest && (["stopped", "aborted", "cancelled"].includes(latest.status) || latest.outcome === "stopped")) {
    return { label: "Stopped", tone: "neutral" };
  }
  if (latest?.status === "completed") return { label: "Done", tone: "success" };
  return tasks.length ? { label: "Ready to build", tone: "neutral" } : { label: "Draft", tone: "neutral" };
}

/** The line under the story's title: "4/7 done · 2 verified · 1 changes · 1 in progress", "4 tasks · nothing built
 * yet", or "No task list yet" before the readiness check agreed one. */
export function storyProgress(tasks: RunTaskItem[]): string {
  if (!tasks.length) return "No task list yet";
  if (!tasks.some((task) => taskStatus(task) !== "open")) {
    return `${tasks.length} task${tasks.length === 1 ? "" : "s"} · nothing built yet`;
  }
  const parts = [`${count(tasks, ["done", "verified"])}/${tasks.length} done`];
  const verified = count(tasks, ["verified"]);
  if (verified) parts.push(`${verified} verified`);
  const changes = count(tasks, ["changes"]);
  if (changes) parts.push(`${changes} changes`);
  const running = count(tasks, ["in_progress"]);
  if (running) parts.push(`${running} in progress`);
  return parts.join(" · ");
}

/** The story's pull request: the newest run that opened one. */
export function storyPullRequest(runs: EpicRun[]): { label: string; url: string | null } | null {
  const pr = runs.find((run) => hasPullRequest(run.pull_request))?.pull_request;
  if (!pr) return null;
  return { label: pr.id ? `PR #${pr.id}` : "Pull request", url: pr.url || null };
}

/** The API cost of all the story's runs. */
export function storyCost(runs: EpicRun[]): number {
  return runs.reduce((sum, run) => sum + (typeof run.cost === "number" ? run.cost : 0), 0);
}

/** What the story's seat calls would cost via the API (list price), summed apart from `storyCost`. */
export function storySeat(runs: EpicRun[]): SeatFigures {
  return totalSeat(runs);
}

/** The run with the decision a person has to take (newest first), for "Open decision". */
export function decisionRun(runs: EpicRun[]): EpicRun | null {
  return runs.find((run) => needsPerson(run) && run.session_id) ?? null;
}

export type EpicSummary = {
  stories: number;
  shipped: number;
  tasks: number;
  tasksDone: number;
  tasksWithChanges: number;
  decisions: number;
  // The API cost, and apart from it the seat's API equivalent (never added together).
  cost: number;
  seat: SeatFigures;
};

/** The epic header's counts: stories shipped, tasks done, tasks with changes, decisions waiting, API cost, seat. */
export function epicSummary(stories: EpicStory[]): EpicSummary {
  const tasks = stories.flatMap((story) => story.tasks);
  const runs = stories.flatMap((story) => story.runs);
  return {
    stories: stories.length,
    shipped: stories.filter(isShipped).length,
    tasks: tasks.length,
    tasksDone: count(tasks, ["done", "verified"]),
    tasksWithChanges: count(tasks, ["changes"]),
    decisions: runs.filter(needsPerson).length,
    cost: storyCost(runs),
    seat: storySeat(runs),
  };
}

/** The story to show open first: the one that needs a person, else the one building; none when all are quiet. */
export function initiallyOpen(stories: EpicStory[]): string | null {
  const first = (label: string) => stories.find((story) => storyStatus(story).label === label)?.item.id;
  return first("Needs you") ?? first("Building") ?? null;
}

/** "1 task", "2 tasks"; "stories" where the plural is not word + s. */
export const plural = (value: number, word: string, many = `${word}s`) => (value === 1 ? word : many);
