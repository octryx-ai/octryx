// Selectable chat options: runtimes, workspaces, workflows, agents and the launch surface.

export type RuntimeOption = {
  value: string;
  label: string;
  provider_name?: string;
  providerName?: string;
  model_id?: string;
  modelId?: string;
  is_automatic?: boolean;
  isAutomatic?: boolean;
  disabled?: boolean;
  disabled_reason?: string;
  disabledReason?: string;
};

export type ProjectOption = {
  id: string;
  name: string;
  is_active?: boolean;
  // The person's default workspace: their private one, else the Instance default set by an administrator.
  isDefault?: boolean;
  // The person's own private workspace; nobody else, administrators included, can see it.
  private?: boolean;
};

// Published workflow definition selectable via workflow_key
// (GET /chat/api/workflows).
export type WorkflowOption = {
  key: string;
  title: string;
  description: string;
  capability: "diagnosis" | "change" | "";
  // The declared capability class (read_only | change | deliver) and the steps with their mode.
  capability_class?: string | null;
  steps?: { tool: string; label: string; required: boolean; mode: "strict" | "guided" }[];
  workflow_id: string;
  workflow_class: string;
  project_id: string | null;
  source: "definition" | "policy";
  // Client-side entry for the explicit "No workflow" choice (workflow_key
  // "none"); only offered while workflow proposals are enabled.
  selection?: "no_workflow";
};

export type AgentModeOption = {
  id: string;
  key: string;
  name: string;
  description: string;
  capability_type: string;
  prompt_instructions: string;
  is_active: boolean;
  is_system: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AgentGroupOption = {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: string;
  projectId?: string;
  position: number;
  isActive: boolean;
  agentCount?: number;
};

export type ChatAgentOption = {
  id: string;
  name: string;
  description: string;
  agentType?: string;
  groupId: string;
  groupName?: string;
  category?: string;
  isCore?: boolean;
  isPrimary?: boolean;
};

export type ChatLaunchSurface = {
  version: number;
  role_scope: string;
  role_names: string[];
  primary_controls: string[];
  advanced_controls: string[];
  explicit_choices: string[];
  derived_choices: string[];
  hidden_choices: string[];
  allow_advanced_overrides: boolean;
  allow_mode_override: boolean;
  allow_agent_override: boolean;
  allow_agent_group_override: boolean;
  allowed_project_ids: string[];
};
