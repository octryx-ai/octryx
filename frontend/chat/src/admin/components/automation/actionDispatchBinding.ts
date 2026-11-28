// An existing Action is never converted implicitly: saves omit dispatch_binding so the stored value is kept.

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

export function offersConversion(task: PanelTaskRow | null): boolean {
  return bindingState(task) === "existing";
}

const DIRECT =
  "Runs the chosen agent directly, under the action's owner, workspace and policies. No registered worker is needed. The server checks the agent when the action is saved and again when it runs.";
const EXISTING =
  "Keeps its existing execution setup: it runs as it is configured today. It is not bound to run its agent directly.";

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
