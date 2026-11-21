

export type AdminUser = {
  id: string;
  username: string;
  email: string;
  display_name: string;
  account_type: string;
  roles: string[];
  groups: Array<{
    id: string;
    name: string;
    description: string;
    is_active: boolean;
    member_count: number;
    created_at: string;
  }>;
  is_active: boolean;
  created_at: string;
};

export type AdminProvider = {
  id: string;
  name: string;
  provider_family: string;
  driver: string;
  runtime_kind: string;
  display_name: string;
  profile_name: string;
  endpoint_url: string;
  binary_path: string;
  is_active: boolean;
  is_global: boolean;
  has_api_key: boolean;
  api_key_masked: string;
  auth_mode: string;
  auth_login: string;
  auth_name: string;
  auth_host: string;
  google_cloud_project: string;
  google_oauth_client_id: string;
  google_oauth_client_configured: boolean;
  config_json: Record<string, unknown>;
  capabilities_json: Record<string, unknown>;
  aws_region: string;
  aws_role_arn: string;
  aws_static_credentials_configured: boolean;
  bootstrap_role: string;
  health_status: string;
  last_health_check_at: string;
  last_health_error: string;
  model_count: number;
  active_model_count: number;
  created_at: string;
};

export type LocalBootstrapStatus = {
  provider_id: string;
  provider_display_name: string;
  endpoint_url: string;
  profile_name: string;
  model_id: string;
  bootstrap_role: string;
  health_status: string;
  last_health_check_at: string;
  last_health_error: string;
  runtime_target_id: string;
  runtime_priority: number | null;
  is_primary: boolean;
  installed: boolean;
  setup_complete: boolean;
  available_models: string[];
  managed_by_system: boolean;
  recommended_endpoint_url: string;
  recommended_model_id: string;
};

export type SetupGuideStep = {
  key: string;
  title: string;
  status: string;
  description: string;
  detail: string;
  blocking: boolean;
  action: string;
  action_label: string;
};

export type SetupGuideStatus = {
  ready: boolean;
  summary: string;
  stats: {
    active_provider_count: number;
    api_provider_count: number;
    local_provider_count: number;
    active_runtime_count: number;
  };
  steps: SetupGuideStep[];
};

export type AdminModel = {
  id: string;
  model_id: string;
  display_name: string;
  context_length: number | null;
  planner_context_budget: number | null;
  max_tokens_per_request: number | null;
  supports_tools: boolean;
  supports_vision: boolean;
  supports_streaming: boolean;
  pricing_input: number | null;
  pricing_output: number | null;
  // Prompt-cache rates, USD per million tokens; null means not priced.
  pricing_cache_read: number | null;
  pricing_cache_write: number | null;
  // The governed contract that owns the prices, if any; manual price edits are refused then.
  cost_source: string | null;
  is_active: boolean;
  last_synced_at: string | null;
};

export type AdminConnector = {
  // Workspace connections of this connector (Automation → Connectors shows its card even without a global entry).
  workspace_connections?: number;
  tool_name: string;
  label: string;
  description: string;
  fields: string[];
  secret_fields: string[];
  supports_test: boolean;
  builtin_tools: { name: string; description: string }[];
  tools: { name: string; description: string }[];
  tool_policy: {
    tool_instructions: string;
    extra_tools: string[];
    disabled_tools: string[];
  };
  is_active: boolean;
  policy_active: boolean;
  configured: boolean;
  public_fields: Record<string, unknown>;
  secret_status: Record<string, boolean>;
  db_id: string | null;
  policy_id: string | null;
  health?: {
    connector_name: string;
    project_id: string;
    status: string;
    response_time_ms: number | null;
    error: string;
    details: string;
    last_checked: string | null;
    updated_at: string | null;
  } | null;
};

export type AdminConnectorHealthLog = {
  id: string;
  connector_name: string;
  project_id: string;
  status: string;
  response_time_ms: number | null;
  error: string;
  details: string;
  checked_at: string | null;
};

export type GitHubConnectorRepository = {
  full_name: string;
  name: string;
  private: boolean;
  default_branch: string;
  html_url: string;
  clone_url: string;
};

export type AdminToolCatalogEntry = {
  name: string;
  description: string;
  default_connector: string | null;
  connectors?: string[];
  is_core: boolean;
  change_only: boolean;
  plan_excluded: boolean;
  plan_only: boolean;
};

export type AdminDatabaseConnector = {
  id: string;
  project_id: string | null;
  name: string;
  description: string;
  db_type: string;
  is_active: boolean;
  public_fields: Record<string, unknown>;
  secret_status: Record<string, boolean>;
  tool_count: number;
  created_at: string | null;
  updated_at: string | null;
  // The stored result of the last real check (null: never checked).
  health?: { status?: string | null; error?: string | null; last_checked?: string | null } | null;
};

export type AdminDatabaseTool = {
  id: string;
  connector_id: string;
  project_id: string | null;
  tool_name: string;
  display_name: string;
  description: string;
  sql_template: string;
  parameters_schema: Record<string, unknown>;
  row_level_security_rules: string[];
  allowed_roles: string[];
  max_rows: number;
  timeout_seconds: number;
  is_active: boolean;
  connector_name: string | null;
  connector_type: string | null;
  created_at: string | null;
  updated_at: string | null;
};
