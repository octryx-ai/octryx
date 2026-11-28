import type { WorkflowOption } from "../../chatOptionTypes";

const CLASS_LABELS: Record<string, string> = { read_only: "Read-only", change: "Change", deliver: "Deliver" };

export function workflowClass(option: Pick<WorkflowOption, "capability" | "capability_class"> | undefined): string {
  if (!option) return "";
  if (option.capability_class && CLASS_LABELS[option.capability_class]) return option.capability_class;
  return option.capability === "diagnosis" ? "read_only" : option.capability === "change" ? "change" : "";
}

export const workflowClassLabel = (value: string): string => CLASS_LABELS[value] ?? "";

export function workflowStepsText(option: Pick<WorkflowOption, "steps"> | undefined): string {
  const steps = option?.steps ?? [];
  if (!steps.length) return "";
  return `Steps: ${steps
    .map((step, index) => `${index + 1} ${step.label || step.tool} (${step.mode})`)
    .join(" · ")}`;
}

// Duplicate titles carry their key so the list tells them apart.
export function workflowOptionTitle(option: Pick<WorkflowOption, "key" | "title">, options: Pick<WorkflowOption, "key" | "title">[]): string {
  const title = (option.title || option.key).trim();
  const same = options.filter((entry) => (entry.title || entry.key).trim().toLowerCase() === title.toLowerCase());
  return same.length > 1 ? `${title} (${option.key})` : title;
}
