// Status comes from what the platform can check, never from what the model says.

import type { StatusTone } from "../../layout/StatusLabel";
import type { RunTaskItem, RunTaskStatus } from "./workflowRunTypes";

export type TaskState = { status: RunTaskStatus; label: string; tone: StatusTone; mark: "check" | "label" | "none" };

const STATES: Record<RunTaskStatus, Omit<TaskState, "status">> = {
  open: { label: "Open", tone: "neutral", mark: "none" },
  in_progress: { label: "In progress", tone: "info", mark: "label" },
  done: { label: "Done: proof test in the change, gates passed", tone: "success", mark: "check" },
  changes: { label: "Changes requested", tone: "problem", mark: "label" },
  verified: { label: "Verified by the review", tone: "success", mark: "check" },
};

export function taskStatus(item: RunTaskItem): RunTaskStatus {
  if (item.status && item.status in STATES) {
    // Older lists without stored statuses come back as open with the proof check in done.
    return item.status === "open" && item.done === true ? "done" : item.status;
  }
  return item.done === true ? "done" : "open";
}

export function taskState(item: RunTaskItem, items: RunTaskItem[] = [item]): TaskState {
  const status = taskStatus(item);
  if (status === "done" && item.status !== "done") return { status, label: "Proof test in the change", tone: "success", mark: "check" };
  if (status === "open" && items.some((other) => taskStatus(other) !== "open")) {
    return { status, label: "Proof test not in the change", tone: "problem", mark: "label" };
  }
  return { status, ...STATES[status] };
}

export function taskProgress(items: RunTaskItem[]): string {
  if (!items.length) return "";
  const count = (wanted: RunTaskStatus[]) => items.filter((item) => wanted.includes(taskStatus(item))).length;
  const started = items.some((item) => taskStatus(item) !== "open");
  if (!started) return `${items.length} task${items.length === 1 ? "" : "s"}`;
  const verified = count(["verified"]);
  const parts = [`${count(["done", "verified"])}/${items.length} done`];
  if (verified) parts.push(`${verified} verified`);
  const changes = count(["changes"]);
  if (changes) parts.push(`${changes} changes`);
  const running = count(["in_progress"]);
  if (running) parts.push(`${running} in progress`);
  return parts.join(" · ");
}
