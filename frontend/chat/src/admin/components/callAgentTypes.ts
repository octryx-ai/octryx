// Call agent admin: config, tool category and runtime model response shapes.
export type CallAgentConfig = {
  id: string;
  name: string;
  project_id: string;
  channel_id: string | null;
  llm_model: string;
  max_tool_calls: number;
  system_prompt: string;
  enabled_tools: string[];
  thinking_message: string;
  is_active: boolean;
};

export type ToolCategory = {
  enabled: Array<{ name: string; description: string }>;
  disabled: Array<{ name: string; description: string }>;
  enabled_count: number;
  disabled_count: number;
};

export type RuntimeModelsResponse = {
  models: Array<{
    id: string;
    name: string;
    display_name: string;
    provider_id: string;
    provider_name: string;
    context_window: number | null;
  }>;
  count: number;
};
