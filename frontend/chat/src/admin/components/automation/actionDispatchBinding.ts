// How an Action is executed: the explicit `dispatch_binding` field. Pure: no requests, no React.
//
// Contract: `dispatch_binding` is always one of "task_definition" (the Action runs its own definition: its
// steps, its Work intake type or its own prompt), "agent_definition" (the Action runs its selected agent
// directly) or "workflow_run". A create always names it; on update an absent field keeps the stored value;
// the server validates the full effective state before any write.
// - A new guided Action always sends "agent_definition".
// - An existing Action is never converted implicitly: only an explicit opt-in on a guided edit of a
//   "task_definition" Action sends it. Every other save omits the field, so the stored value is kept.
// - The text describes the Action's current setting for its next runs. There is no per-run record of
//   the binding, so it never describes past runs.
// - "task_definition" says only that the Action's own execution setup is kept. How such an Action is routed
//   (worker, deterministic local steps, ...) is decided by the backend; this module never re-derives it.

import type { PanelTaskRow } from "../taskTypes";

export const AGENT_DEFINITION_BINDING = "agent_definition";
export const TASK_DEFINITION_BINDING = "task_definition";

export type BindingState =
  | "agent_definition"
  | "existing"
  | "unreported"
  | "unknown";

export function bindingState(task: PanelTaskRow | null): BindingState {
  if (!task || !("dispatch_binding" in task) || task.dispatch_binding === undefined) {
    return "unreported";
  }
  if (task.dispatch_binding === TASK_DEFINITION_BINDING) return "existing";
  if (task.dispatch_binding === AGENT_DEFINITION_BINDING) return "agent_definition";
  return "unknown";
}

/** The value a guided save sends, or undefined to omit the field (the stored value is kept). */
export function bindingToSend({
  task,
  convert,
}: {
  task: PanelTaskRow | null;
  convert: boolean;
}): typeof AGENT_DEFINITION_BINDING | undefined {
  if (!task) return AGENT_DEFINITION_BINDING;
  return convert && bindingState(task) === "existing"
    ? AGENT_DEFINITION_BINDING
    : undefined;
}

/** Whether a guided edit offers the explicit conversion of an Action without an explicit binding. */
export function offersConversion(task: PanelTaskRow | null): boolean {
  return bindingState(task) === "existing";
}

const DIRECT =
  "Runs the chosen agent directly, under the action's owner, workspace and policies. No registered worker is needed. The server checks the agent when the action is saved and again when it runs.";
const EXISTING =
  "Keeps its existing execution setup: it runs as it is configured today. It is not bound to run its agent directly.";

/** The guided form's "How it runs" text for the current setting (a new Action is always direct). */
export function guidedBindingText(task: PanelTaskRow | null): string {
  if (!task) return DIRECT;
  switch (bindingState(task)) {
    case "agent_definition":
      return DIRECT;
    case "existing":
      return EXISTING;
    case "unknown":
      return "This server reports an execution setting this form does not know. Saving here keeps it unchanged.";
    default:
      return "This server does not report how this action runs. Saving here keeps it unchanged.";
  }
}

/** The card badge for the current setting; nothing when the server does not report it. */
export function bindingBadge(
  task: PanelTaskRow,
): { label: string; title: string } | null {
  const future = " This is the current setting for its next runs; earlier runs are not labelled with it.";
  switch (bindingState(task)) {
    case "agent_definition":
      return { label: "Runs agent directly", title: DIRECT + future };
    case "existing":
      return { label: "Existing execution setup", title: EXISTING + future };
    case "unknown":
      return {
        label: "Execution setting unknown",
        title: "This server reports an execution setting this page does not know.",
      };
    default:
      return null;
  }
}
