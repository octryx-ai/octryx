export type ToolSurface = "governed" | "none";

export const TOOL_SURFACE_DEFAULT: ToolSurface = "governed";

export const TOOL_SURFACE_OPTIONS: { value: ToolSurface; label: string; help: string }[] = [
  {
    value: "governed",
    label: "Policy-governed tools",
    help: "The agent may use the tools its mode, workspace connectors and policies allow. Approval and denial rules still apply.",
  },
  {
    value: "none",
    label: "No tools (text only)",
    help: "The agent cannot call any tool, including tool-based workflows, files, searches and connectors. It answers from its instructions and the conversation, and can still run as a step in a workflow.",
  },
];

export function isToolSurface(value: unknown): value is ToolSurface {
  return value === "governed" || value === "none";
}

// Read like the runtime: a missing key means "governed"; any other non-enum value stays unknown so saving waits for a choice.
export function toolSurfaceFromAgent(agent: { toolSurface?: unknown } | null | undefined): string {
  if (!agent || !("toolSurface" in agent) || agent.toolSurface === undefined) return TOOL_SURFACE_DEFAULT;
  const value = agent.toolSurface;
  return typeof value === "string" ? value : String(value);
}

export function toolSurfaceLabel(value: string): string {
  return TOOL_SURFACE_OPTIONS.find((option) => option.value === value)?.label ?? `Unknown tool setting (${value || "empty"})`;
}

export function toolSurfaceForSave(value: string): { ok: true; value: ToolSurface } | { ok: false; error: string } {
  return isToolSurface(value)
    ? { ok: true, value }
    : { ok: false, error: `This agent has an unknown tool setting (${value || "empty"}). Choose Policy-governed tools or No tools before saving.` };
}

type StepLike = { name?: string; isEnabled?: unknown; allowedTools?: unknown[] | null; stepConfig?: Record<string, unknown> | null };

// Same rule as the server's step_needs_tools: an unrecognised tool_use value counts as required.
export function stepNeedsTools(step: StepLike): boolean {
  if (!step.isEnabled) return false;
  if ((step.allowedTools ?? []).some((tool) => String(tool ?? "").trim() !== "")) return true;
  const raw = step.stepConfig?.tool_use;
  return raw !== undefined && raw !== null && String(raw).trim().toLowerCase() !== "optional";
}

export function stepsNeedingTools(steps: StepLike[] | null | undefined): string[] {
  return (steps ?? []).flatMap((step, index) => (stepNeedsTools(step) ? [step.name?.trim() || `Step ${index + 1}`] : []));
}
