// What an agent declares besides its texts. The capability ceiling caps the
// class a workflow may give it (it never grants), the default workflow applies when a turn names the agent and no
// workflow, and the execution mode names the agent's work-item envelope (coding delivery).
import type { CapabilityClass } from "../agentsWorkflows/awBadges";

export type ExecutionMode = "" | "coding_delivery";

export type AgentSetupFields = {
  capabilityCeiling: CapabilityClass;
  defaultWorkflowKey: string;
  executionMode: ExecutionMode;
};

export const DEFAULT_AGENT_SETUP: AgentSetupFields = {
  capabilityCeiling: "read_only",
  defaultWorkflowKey: "",
  executionMode: "",
};

export const CEILING_OPTIONS: { value: CapabilityClass; title: string; description: string }[] = [
  { value: "read_only", title: "Read-only", description: "Never edits, even in a change workflow." },
  { value: "change", title: "Change", description: "May run change workflows." },
  { value: "deliver", title: "Deliver", description: "May run deliver workflows." },
];

export const EXECUTION_MODE_OPTIONS: { value: ExecutionMode; label: string }[] = [
  { value: "", label: "Chat agent" },
  { value: "coding_delivery", label: "Coding delivery (scheduled runs get a work item)" },
];

const CEILINGS = new Set<string>(["read_only", "change", "deliver"]);
const MODES = new Set<string>(["", "coding_delivery"]);

export function agentSetupFromAgent(agent: {
  capabilityCeiling?: string;
  defaultWorkflowKey?: string;
  executionMode?: string;
}): AgentSetupFields {
  const ceiling = String(agent.capabilityCeiling || "read_only");
  const mode = String(agent.executionMode || "");
  return {
    capabilityCeiling: (CEILINGS.has(ceiling) ? ceiling : "read_only") as CapabilityClass,
    defaultWorkflowKey: String(agent.defaultWorkflowKey || ""),
    executionMode: (MODES.has(mode) ? mode : "") as ExecutionMode,
  };
}
