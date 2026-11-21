// The agent's plan inline in the transcript, like the execution diff.
// The plan is what the turn already recorded: the last successful `todo_write`
// call of the message (its `todos` parameter, which the tool validated and
// stored). Read-only and minimal: no new server data, no prompt text. Pure
// functions only, so the unit harness can load them.

import type { ToolEvent } from "../chatThreadTypes";

export type TurnPlanStepStatus = "pending" | "in_progress" | "completed";

export type TurnPlanStep = {
  id: string;
  subject: string;
  status: TurnPlanStepStatus;
};

export type TurnPlanView = {
  steps: TurnPlanStep[];
  completed: number;
  total: number;
  // The step in progress, if any (the plan's "now").
  current: string | null;
  // More steps were recorded than the view shows.
  truncated: boolean;
};

export const PLAN_TOOL_NAME = "todo_write";
export const PLAN_MAX_STEPS = 30;
export const PLAN_SUBJECT_MAX_CHARS = 160;
const STEP_STATUSES: ReadonlyArray<TurnPlanStepStatus> = [
  "pending",
  "in_progress",
  "completed",
];

function planStep(value: unknown): TurnPlanStep | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const subject =
    typeof record.subject === "string"
      ? record.subject.replace(/\s+/g, " ").trim()
      : "";
  const id =
    typeof record.id === "string" || typeof record.id === "number"
      ? String(record.id)
      : "";
  if (!subject || !id) {
    return null;
  }
  const status =
    STEP_STATUSES.find((entry) => entry === record.status) ?? "pending";
  return {
    id,
    subject:
      subject.length > PLAN_SUBJECT_MAX_CHARS
        ? `${subject.slice(0, PLAN_SUBJECT_MAX_CHARS - 1)}…`
        : subject,
    status,
  };
}

function succeeded(event: ToolEvent): boolean {
  const result = event.result;
  const resultError =
    result &&
    typeof result === "object" &&
    !Array.isArray(result) &&
    "error" in result;
  return event.status === "success" && !resultError;
}

/** The plan of a message's tool events, or `null` when the turn recorded none. */
export function turnPlanFromToolEvents(
  events: ToolEvent[] | null | undefined,
): TurnPlanView | null {
  const recorded = (events ?? []).filter(
    (event) => event.toolName === PLAN_TOOL_NAME && succeeded(event),
  );
  const last = recorded[recorded.length - 1];
  const todos = last?.parameters?.todos;
  if (!Array.isArray(todos)) {
    return null;
  }
  const all = todos
    .map(planStep)
    .filter((step): step is TurnPlanStep => step !== null);
  if (!all.length) {
    return null;
  }
  const steps = all.slice(0, PLAN_MAX_STEPS);
  return {
    steps,
    completed: all.filter((step) => step.status === "completed").length,
    total: all.length,
    current: all.find((step) => step.status === "in_progress")?.subject ?? null,
    truncated: all.length > steps.length,
  };
}

export function planStepMarker(status: TurnPlanStepStatus): string {
  if (status === "completed") return "✓";
  if (status === "in_progress") return "▸";
  return "○";
}
