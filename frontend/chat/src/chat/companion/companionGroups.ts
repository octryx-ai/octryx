// Octryx companion: which items need the person, which are done or problems, and the panel's four groups.
import type { AttentionGroups, AttentionItem, AttentionKind, RunningAgent } from "./companionTypes";

export const NEEDS_YOU: AttentionKind[] = ["question", "gate", "device_approval", "handover"];

/** The runs the "Running" section lists: still going (working, needs you); finished and problem runs are not. */
export function runningNow(running: RunningAgent[]): RunningAgent[] {
  return running.filter((run) => run.state === "working" || run.state === "needs_you");
}

export const needsYou = (items: AttentionItem[]) => items.filter((item) => NEEDS_YOU.includes(item.kind) || item.severity === "action");
// A finished Mac turn (kind "turn", severity info) is done, a failed one (warning) a problem (outsider walkthrough
// "Finished on your Mac · Success" stood under Problems and counted in the badge).
export const isDone = (item: AttentionItem) => item.kind === "done" || (item.kind === "turn" && item.severity === "info");
export const doneItems = (items: AttentionItem[]) => items.filter(isDone);
export const problemItems = (items: AttentionItem[]) =>
  items.filter((item) => !needsYou([item]).length && !isDone(item));


/**
 * The panel's four groups, each run in exactly one: Needs you > Problems > Running > Done. A run waiting
 * for an approval is under Needs you only, a finished item of a run that still goes is not under Done as well. Items
 * without a run are grouped by their kind alone.
 */
export function groupAttention(items: AttentionItem[], running: RunningAgent[]): AttentionGroups {
  const taken = new Set<string>();
  const claim = (runId: string | null) => { if (runId) taken.add(runId); };
  const free = (runId: string | null) => !runId || !taken.has(runId);
  const needs = needsYou(items);
  needs.forEach((item) => claim(item.runId));
  const problems = problemItems(items).filter((item) => free(item.runId));
  problems.forEach((item) => claim(item.runId));
  const runs = runningNow(running).filter((run) => free(run.key));
  runs.forEach((run) => claim(run.key));
  const done = doneItems(items).filter((item) => free(item.runId));
  return { needs, problems, running: runs, done };
}

/** The one count rule: the badge and the header count what needs you plus the problems, each run once. */
export const badgeCount = (items: AttentionItem[]) => {
  const groups = groupAttention(items, []);
  return groups.needs.length + groups.problems.length;
};
