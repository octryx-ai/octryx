import { decisionPrimary } from "./decisionCardModel";
import type { StatusTone } from "../../layout/StatusLabel";
import { runAdoptedTexts } from "./workflowRunModel";
import { type RunAction, type WorkflowRun } from "./workflowRunTypes";

export type RunStepState = "done" | "active" | "problem" | "pending";
export type RunStep = { id: string; title: string; state: RunStepState };

export function runSteps(run: Pick<WorkflowRun, "nodes" | "current_node" | "status" | "phase_position">): RunStep[] {
  const phases = (run.nodes ?? []).filter((node) => node.kind === "phase" || node.kind === "parallel_work");
  if (!phases.length) return [];
  const currentId = run.current_node?.id ?? null;
  let activeIndex = phases.findIndex((node) => node.id === currentId);
  if (activeIndex < 0 && run.phase_position?.index) activeIndex = run.phase_position.index - 1;
  // On a decision between phases, the phases before it in the graph are done.
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

export function runNeedsYou(run: Pick<WorkflowRun, "status" | "actions">): boolean {
  return (run.status === "waiting" || run.status === "paused") && run.actions.some((action) => action.tone !== "danger");
}

export function runNextAction(run: Pick<WorkflowRun, "status" | "actions"> & Partial<Pick<WorkflowRun, "waiting">>): RunAction | null {
  if (!runNeedsYou(run)) return null;
  // A product owner's decision follows the review: "changes" makes another round the primary, not shipping.
  const decided = decisionPrimary({ actions: run.actions, waiting: run.waiting });
  if (decided) return decided;
  return run.actions.find((action) => action.tone !== "danger") ?? null;
}

export function runActionsInOrder(run: Pick<WorkflowRun, "status" | "actions"> & Partial<Pick<WorkflowRun, "waiting">>): RunAction[] {
  const next = runNextAction(run);
  const rest = run.actions.filter((action) => action !== next);
  return [
    ...(next ? [next] : []),
    ...rest.filter((action) => action.tone !== "danger"),
    ...rest.filter((action) => action.tone === "danger"),
  ];
}

export function runCounterTexts(run: Pick<WorkflowRun, "loops">): string[] {
  return (run.loops ?? []).filter((loop) => loop.limit > 0 && loop.used > 0).map((loop) => `${loop.title} ${loop.used}/${loop.limit}`);
}

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

export function runShortState(run: Pick<WorkflowRun, "status" | "actions">): string {
  if (runNeedsYou(run)) return "Waiting for you";
  return SHORT_STATE[run.status] ?? run.status;
}

export function runThreadTitle(run: Pick<WorkflowRun, "title" | "work_item" | "status" | "actions">): string {
  const subject = run.work_item ? `${run.work_item.key} ${run.work_item.title}`.trim() : run.title;
  return `${subject} · ${runShortState(run)}`;
}

// The header names the run's subject when the chat is titled by its first prompt; a title a run or a person gave the
// chat stays (a review of a Work item's pull request is not that Work item's own chat).
export function runChatTitle(
  run: Pick<WorkflowRun, "title" | "work_item" | "status" | "actions">,
  chat?: { title?: string | null; titleSource?: string | null } | null,
): string {
  const title = chat?.title?.trim();
  if (!title || !chat?.titleSource || chat.titleSource === "prompt") return runThreadTitle(run);
  return `${title} · ${runShortState(run)}`;
}

export function runStateTone(run: Pick<WorkflowRun, "status" | "actions">): StatusTone {
  if (run.status === "failed") return "problem";
  if (runNeedsYou(run) || run.status === "paused") return "attention";
  return "neutral";
}
