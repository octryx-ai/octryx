// The run card above a run's chat: on top only the phases as steps, the state and the next
// action the person can take; loop counters only once one was used; provenance (runs taken over, ids) in Details.
// Pure functions, so the unit tests read them directly.

import { decisionPrimary } from "./decisionCardModel";
import type { StatusTone } from "../../layout/StatusLabel";
import { runAdoptedTexts, runSliceTexts } from "./workflowRunModel";
import { type RunAction, type WorkflowRun } from "./workflowRunTypes";

export type RunStepState = "done" | "active" | "problem" | "pending";
export type RunStep = { id: string; title: string; state: RunStepState };

/** The run's phases (and Parallel work boxes, which do a phase's work) as steps; empty for a run without phases. */
export function runSteps(run: Pick<WorkflowRun, "nodes" | "current_node" | "status" | "phase_position">): RunStep[] {
  const phases = (run.nodes ?? []).filter((node) => node.kind === "phase" || node.kind === "parallel_work");
  if (!phases.length) return [];
  const currentId = run.current_node?.id ?? null;
  let activeIndex = phases.findIndex((node) => node.id === currentId);
  if (activeIndex < 0 && run.phase_position?.index) activeIndex = run.phase_position.index - 1;
  // On a decision between phases (not a phase itself): the phases before it in the graph are done.
  const nodeIndex = activeIndex < 0 && currentId ? (run.nodes ?? []).findIndex((node) => node.id === currentId) : -1;
  return phases.map((node, index) => {
    let state: RunStepState = "pending";
    if (run.status === "completed") state = "done";
    else if (nodeIndex >= 0 && (run.nodes ?? []).indexOf(node) < nodeIndex) state = "done";
    else if (activeIndex >= 0 && index < activeIndex) state = "done";
    else if (index === activeIndex) state = run.status === "failed" || run.status === "paused" ? "problem" : "active";
    return { id: node.id, title: node.title || node.id, state };
  });
}

/** Whether the run waits for the person who sees it (a decision, a reply, a retry). */
export function runNeedsYou(run: Pick<WorkflowRun, "status" | "actions">): boolean {
  return (run.status === "waiting" || run.status === "paused") && run.actions.some((action) => action.tone !== "danger");
}

/** The one action shown as primary: the first non-destructive one while the run waits for the person. */
export function runNextAction(run: Pick<WorkflowRun, "status" | "actions"> & Partial<Pick<WorkflowRun, "waiting">>): RunAction | null {
  if (!runNeedsYou(run)) return null;
  // A product owner's decision follows the review: "changes" makes another round the primary, not shipping.
  const decided = decisionPrimary({ actions: run.actions, waiting: run.waiting });
  if (decided) return decided;
  return run.actions.find((action) => action.tone !== "danger") ?? null;
}

/** All actions in display order: the next action first, the others neutral, destructive ones last. */
export function runActionsInOrder(run: Pick<WorkflowRun, "status" | "actions"> & Partial<Pick<WorkflowRun, "waiting">>): RunAction[] {
  const next = runNextAction(run);
  const rest = run.actions.filter((action) => action !== next);
  return [
    ...(next ? [next] : []),
    ...rest.filter((action) => action.tone !== "danger"),
    ...rest.filter((action) => action.tone === "danger"),
  ];
}

/** Loop counters, only those already used ("Implement ↔ test 2/3"); untouched loops say nothing. */
export function runCounterTexts(run: Pick<WorkflowRun, "loops" | "slices">): string[] {
  return [
    ...(run.loops ?? []).filter((loop) => loop.limit > 0 && loop.used > 0).map((loop) => `${loop.title} ${loop.used}/${loop.limit}`),
    ...runSliceTexts(run as WorkflowRun),
  ];
}

/** What only Details shows: the workflow version, what was taken over from earlier runs (with their ids), the run id. */
export function runDetailTexts(run: Pick<WorkflowRun, "id" | "workflow_key" | "workflow_version" | "adopted">): string[] {
  return [
    `Workflow ${run.workflow_key}${run.workflow_version ? ` · version ${run.workflow_version}` : ""}`,
    ...runAdoptedTexts(run),
    `Run ${run.id}`,
  ];
}

const SHORT_STATE: Record<string, string> = {
  running: "Working",
  waiting: "Waiting",
  paused: "Paused",
  completed: "Done",
  stopped: "Stopped",
  failed: "Failed",
};

/** The short state of a run thread's title: "Waiting for you" when the person must act. */
export function runShortState(run: Pick<WorkflowRun, "status" | "actions">): string {
  if (runNeedsYou(run)) return "Waiting for you";
  return SHORT_STATE[run.status] ?? run.status;
}

/** The title of a run's chat: Work item (or run title) and the current state, e.g. " Login fix · Waiting for you". */
export function runThreadTitle(run: Pick<WorkflowRun, "title" | "work_item" | "status" | "actions">): string {
  const subject = run.work_item ? `${run.work_item.key} ${run.work_item.title}`.trim() : run.title;
  return `${subject} · ${runShortState(run)}`;
}

/** The state label's tone: colour only for exceptions (the person must act, something failed). */
export function runStateTone(run: Pick<WorkflowRun, "status" | "actions">): StatusTone {
  if (run.status === "failed") return "problem";
  if (runNeedsYou(run) || run.status === "paused") return "attention";
  return "neutral";
}
