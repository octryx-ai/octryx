// Admin agent types: agent definitions, steps and builder metadata.
import type { AgentModeOption, ProjectOption, RuntimeOption } from "../../chatOptionTypes";

export type PanelAgentStep = {
  id: string;
  position: number;
  name: string;
  stepType: string;
  instructions: string;
  successCriteria: string;
  allowedTools: string[];
  stepConfig?: Record<string, unknown>;
  isEnabled: boolean;
};

export type PanelAgent = {
  id: string;
  name: string;
  description: string;
  goal?: string;
  agent_type: string;
  agentType?: string;
  thinkingLevel?: string;
  branchPrefix?: string;
  requireSelfReview?: boolean;
  // "governed" | "none"; absent on a create payload that keeps the default.
  toolSurface?: string;
  // The checked output format: {kind: "text"} or {kind: "json_object", schema}; absent means free
  // text. Typed unknown because a saved value may be one the form cannot represent (agentReplyFormat).
  replyContract?: unknown;
  systemPrompt?: string;
  outputPrompt?: string;
  projectId?: string;
  runtimeTargetId?: string;
  skillPreferences?: {
    preferred_skill_ids?: string[];
    blocked_skill_ids?: string[];
  };
  groupId?: string;
  groupName?: string;
  step_count: number;
  is_active: boolean;
  isActive?: boolean;
  steps?: PanelAgentStep[];
  executionMode?: string;
  // Built-in agents ship with the platform; the ceiling caps what a workflow may give the agent.
  builtinKey?: string;
  capabilityCeiling?: string;
  defaultWorkflowKey?: string;
};

export type AdminAgentMode = AgentModeOption;

export type AgentBuilderMeta = {
  projects: ProjectOption[];
  runtime_options: RuntimeOption[];
  agent_groups?: Array<{
    id: string;
    name: string;
    slug: string;
    description: string;
    category: string;
    projectId?: string;
    position: number;
    isActive: boolean;
  }>;
  thinking_levels: string[];
  agent_modes: AdminAgentMode[];
  step_type_options: string[];
  tool_options: string[];
  owner_id: string;
};
