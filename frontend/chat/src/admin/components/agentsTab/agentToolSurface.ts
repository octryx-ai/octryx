// The agent's tool setting: `toolSurface` on the panel agent payload and on create/update.
// "governed" offers the tools the agent's mode, workspace connectors and policies allow (the
// default); "none" runs the agent text-only.
// The server owns validation: it refuses "none" while steps list tools or require tool use, and it
// rejects unknown values. Nothing here infers the setting from the goal, the steps or the model.

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

// The form value of a saved agent, read exactly like the runtime does (services/agent_tool_surface.py,
// payload_tool_surface): a missing key means "governed"; a present value is kept verbatim, with no
// trimming, so null, "", " none" or any other non-enum value shows as unknown (the runtime refuses
// it) and saving waits for an explicit choice.
export function toolSurfaceFromAgent(agent: { toolSurface?: unknown } | null | undefined): string {
  if (!agent || !("toolSurface" in agent) || agent.toolSurface === undefined) return TOOL_SURFACE_DEFAULT;
  const value = agent.toolSurface;
  return typeof value === "string" ? value : String(value);
}

export function toolSurfaceLabel(value: string): string {
  return TOOL_SURFACE_OPTIONS.find((option) => option.value === value)?.label ?? `Unknown tool setting (${value || "empty"})`;
}

// The value to send. An unknown value is never sent back silently: the author has to choose.
export function toolSurfaceForSave(value: string): { ok: true; value: ToolSurface } | { ok: false; error: string } {
  return isToolSurface(value)
    ? { ok: true, value }
    : { ok: false, error: `This agent has an unknown tool setting (${value || "empty"}). Choose Policy-governed tools or No tools before saving.` };
}

type StepLike = { name?: string; isEnabled?: unknown; allowedTools?: unknown[] | null; stepConfig?: Record<string, unknown> | null };

// The server's conflict rule (services/agent_tool_surface.py, step_needs_tools): an enabled step
// needs tools when it lists a non-blank allowed tool, or when its tool_use is set to anything other
// than "optional" (case and spaces ignored), since an unrecognised value counts as required.
export function stepNeedsTools(step: StepLike): boolean {
  if (!step.isEnabled) return false;
  if ((step.allowedTools ?? []).some((tool) => String(tool ?? "").trim() !== "")) return true;
  const raw = step.stepConfig?.tool_use;
  return raw !== undefined && raw !== null && String(raw).trim().toLowerCase() !== "optional";
}

// Steps the server refuses together with "No tools" (HTTP 409), named before saving so nothing is
// removed or changed behind the author's back. The server stays the authority.
export function stepsNeedingTools(steps: StepLike[] | null | undefined): string[] {
  return (steps ?? []).flatMap((step, index) => (stepNeedsTools(step) ? [step.name?.trim() || `Step ${index + 1}`] : []));
}
