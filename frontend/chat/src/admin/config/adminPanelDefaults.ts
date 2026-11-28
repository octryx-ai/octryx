import type { AdminRuntimeSettings } from "../types/adminPanelTypes.runtimeCorp";

export const DEFAULT_RUNTIME_SETTINGS: AdminRuntimeSettings = {
  max_output_tokens_default: null,
  agent_default_model: "",
  execution_runtime_provider: "host",
  auth_oidc_only: false,
  execution_runtime_docker_image: "python:3.11-slim",
  execution_runtime_docker_network_mode: "none",
  execution_runtime_allow_host_fallback: false,
  session_workspace_base_dir: "",
  session_workspace_max_age_hours: 24,
  session_workspace_storage_backend: "disabled",
  session_workspace_storage_bucket: "",
  session_workspace_storage_prefix: "",
  session_workspace_sync_excluded_dirs: "",
  session_workspace_sync_default_excluded_dirs: [],
  session_workspace_sync_excluded_globs: "",
  session_workspace_sync_default_excluded_globs: [],
  session_workspace_sync_max_file_size_bytes: 0,
  session_workspace_sync_max_file_count: 5000,
  office_template_library: [],
  llm_security_analyzer_timeout_seconds: 8,
  llm_security_analyzer_review_threshold: 40,
  llm_security_analyzer_deny_threshold: 80,
  security_analyzer_chain: [],
  security_analyzer_options: [],
  approx_chars_per_token: 4,
  trace_max_string: 16000,
  trace_max_list_items: 200,
  trace_max_dict_items: 120,
  saved_script_max_output_chars: 8000,
  runtime_request_timeout_seconds: 90,
  // "" is the governed "unset" state: each driver applies its own default.
  runtime_fallback_mode: "",
  agent_session_cost_limit_usd: 5,
  agent_request_cost_limit_usd: 1.5,
  cost_limit_scope: {
    scope: "global",
    project_id: "",
    session_source: "global",
    request_source: "global",
    project_session_cost_limit_usd: null,
    project_request_cost_limit_usd: null,
  },
};

export function createDefaultGithubConnectorRepoForm() {
  return {
    name: "",
    description: "",
    owner: "",
    owner_type: "org",
    visibility: "private",
    default_branch: "main",
    local_path: "",
    create_readme: true,
    create_gitignore: true,
    initial_commit: true,
    register_code_repository: false,
    project_id: "",
    index_backend: "auto",
    semantic_backend: "auto",
    structure_backend: "auto",
    graph_backend: "auto",
  };
}

export function createDefaultDatabaseConnectorForm() {
  return {
    name: "",
    description: "",
    db_type: "postgresql",
    host: "",
    port: "",
    database: "",
    username: "",
    password: "",
    dsn: "",
    driver: "",
    file_path: "",
    is_active: true,
  };
}

export function createDefaultDatabaseToolForm() {
  return {
    connector_id: "",
    tool_name: "database_tool_",
    display_name: "",
    description: "",
    sql_template: "select 1 as example",
    parameters_schema:
      '{\n  "type": "object",\n  "properties": {},\n  "required": []\n}',
    row_level_security_rules: "tenant_id = $user.id",
    allowed_roles: "",
    max_rows: "100",
    timeout_seconds: "30",
    is_active: true,
  };
}
