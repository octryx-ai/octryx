// The selected workflow's class and steps in the composer: what the next turn may do and what it must
// produce. Pure; the workflow chip renders it.
import type { WorkflowOption } from "../../chatOptionTypes";

const CLASS_LABELS: Record<string, string> = { read_only: "Read-only", change: "Change", deliver: "Deliver" };

// The declared capability class, else the Diagnosis/Change capability mapped onto a class.
export function workflowClass(option: Pick<WorkflowOption, "capability" | "capability_class"> | undefined): string {
  if (!option) return "";
  if (option.capability_class && CLASS_LABELS[option.capability_class]) return option.capability_class;
  return option.capability === "diagnosis" ? "read_only" : option.capability === "change" ? "change" : "";
}

export const workflowClassLabel = (value: string): string => CLASS_LABELS[value] ?? "";

// "Steps: 1 Search sources (strict) · 2 Summarize (guided)"; empty without declared steps.
export function workflowStepsText(option: Pick<WorkflowOption, "steps"> | undefined): string {
  const steps = option?.steps ?? [];
  if (!steps.length) return "";
  return `Steps: ${steps
    .map((step, index) => `${index + 1} ${step.label || step.tool} (${step.mode})`)
    .join(" · ")}`;
}

// Two workflows with the same title (two keys named "Companion acceptance fixture") would read as one listed twice;
// each then carries its key, so the list tells them apart.
export function workflowOptionTitle(option: Pick<WorkflowOption, "key" | "title">, options: Pick<WorkflowOption, "key" | "title">[]): string {
  const title = (option.title || option.key).trim();
  const same = options.filter((entry) => (entry.title || entry.key).trim().toLowerCase() === title.toLowerCase());
  return same.length > 1 ? `${title} (${option.key})` : title;
}
