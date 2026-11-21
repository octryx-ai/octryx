// Workspace agent catalog types of the projects panel payload.
export type AdminProjectAgentCatalogItem = {
  id: string;
  name: string;
  description: string;
  goal: string;
  agent_type: string;
  category_key: string;
  category_label: string;
  is_core: boolean;
  group_id: string;
  group_name: string;
  runtime_target_id: string;
  step_count: number;
  primary_score: number;
  preference_status: string;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminProjectAgentRoleSummary = {
  category_key: string;
  category_label: string;
  is_core: boolean;
  agent_count: number;
  primary_agent_name: string;
  primary_agent_id: string;
  consolidation_candidates: string[];
  recommendation: string;
  agents: AdminProjectAgentCatalogItem[];
};
