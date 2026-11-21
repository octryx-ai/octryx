import type { SetupGuideStep } from "../../types/adminPanelTypes.usersProviders";

// Required and optional open steps are counted separately (judge):
// an optional recommendation must not read as a failed required setup.
export function setupGuideOpenSummary(steps: SetupGuideStep[]): string {
  const open = steps.filter((step) => step.status !== "completed");
  const required = open.filter((step) => step.blocking).length;
  const optional = open.length - required;
  if (!open.length) return "All steps done";
  const parts: string[] = [];
  if (required) parts.push(`${required} required step${required === 1 ? "" : "s"} open`);
  if (optional) parts.push(`${optional} optional recommendation${optional === 1 ? "" : "s"}`);
  return parts.join(" · ");
}
