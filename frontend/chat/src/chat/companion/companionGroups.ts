import type { AttentionGroups, AttentionItem, AttentionKind, RunningAgent } from "./companionTypes";

export const NEEDS_YOU: AttentionKind[] = ["question", "gate", "device_approval", "handover", "pool"];

export function runningNow(running: RunningAgent[]): RunningAgent[] {
  return running.filter((run) => run.state === "working" || run.state === "needs_you");
}

export const needsYou = (items: AttentionItem[]) => items.filter((item) => NEEDS_YOU.includes(item.kind) || item.severity === "action");
export const isDone = (item: AttentionItem) => item.kind === "done" || (item.kind === "turn" && item.severity === "info");
export const doneItems = (items: AttentionItem[]) => items.filter(isDone);
export const problemItems = (items: AttentionItem[]) =>
  items.filter((item) => !needsYou([item]).length && !isDone(item));


/** Each run lands in exactly one group: Needs you > Problems > Running > Done. */
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
