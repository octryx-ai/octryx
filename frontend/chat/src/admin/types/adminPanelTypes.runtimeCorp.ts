export type AdminRuntime = {
  id: string;
  provider_id: string;
  provider_name: string;
  provider_display_name: string;
  model_id: string;
  supports_tools: boolean | null;
  supports_vision: boolean | null;
  priority: number;
  is_active: boolean;
  use_case_tags: string[];
  /** Governed model capabilities, validated against the capability catalog. */
  capability_tags?: string[];
  /** Sampling override: false = never send a temperature, null = the sampling catalog decides. */
  accepts_temperature?: boolean | null;
  /** What the provider client will actually send (the model catalog's temperature or never send), and why. */
  temperature_effective?: {
    mode: "sent" | "model_default" | "not_sent" | "driver_managed";
    value: number | null;
    reason: string;
    label: string;
  };
  /** A gateway alias whose upstream model rejects a temperature. */
  temperature_warning?: string | null;
};

export type AdminOfficeTemplateEntry = {
  key: string;
  name: string;
  doc_type: "docx" | "xlsx" | "pptx";
  path: string;
  description: string;
  is_default: boolean;
  source_path?: string;
  ai_template_path?: string;
  package_manifest_path?: string;
  storage_contract?: {
    doc_type?: string;
    storage_kind?: string;
    source_path?: string;
    active_template_path?: string;
    package_root?: string;
    package_manifest_path?: string;
    generated_artifact_root?: string;
    ai_template_path?: string;
    has_import_package?: boolean;
    has_generated_ai_artifact?: boolean;
  };
};

export type OfficeTemplateType = "pptx" | "docx" | "xlsx";

export type OfficeTemplateEntry = {
  template_id: string;
  type: OfficeTemplateType;
  source_path: string;
  display_name: string;
  source_file_name: string;
  description?: string;
  created_at: string | null;
};

export type OfficeTemplateEntryMap = {
  pptx: OfficeTemplateEntry[];
  docx: OfficeTemplateEntry[];
  xlsx: OfficeTemplateEntry[];
};

export type AdminRuntimeSettings = {
  max_output_tokens_default: number | null;
  agent_default_model: string;
  execution_runtime_provider: "host" | "docker";
  auth_oidc_only: boolean;
  execution_runtime_docker_image: string;
  execution_runtime_docker_network_mode: "none" | "bridge" | "host";
  execution_runtime_allow_host_fallback: boolean;
  session_workspace_base_dir: string;
  session_workspace_max_age_hours: number;
  session_workspace_storage_backend: "disabled" | "filesystem" | "s3";
  session_workspace_storage_bucket: string;
  session_workspace_storage_prefix: string;
  session_workspace_sync_excluded_dirs: string;
  session_workspace_sync_default_excluded_dirs: string[];
  session_workspace_sync_excluded_globs: string;
  session_workspace_sync_default_excluded_globs: string[];
  session_workspace_sync_max_file_size_bytes: number;
  session_workspace_sync_max_file_count: number;
  office_template_library: AdminOfficeTemplateEntry[];
  llm_security_analyzer_timeout_seconds: number;
  llm_security_analyzer_review_threshold: number;
  llm_security_analyzer_deny_threshold: number;
  security_analyzer_chain: string[];
  security_analyzer_options: Array<{
    key: string;
    label: string;
    description: string;
  }>;
  default_completion_tokens: number;
  extended_completion_tokens: number;
  approx_chars_per_token: number;
  trace_max_string: number;
  trace_max_list_items: number;
  trace_max_dict_items: number;
  saved_script_max_output_chars: number;
  runtime_request_timeout_seconds: number;
  /** Governed cross-runtime fallback mode; "" means the per-driver default. */
  runtime_fallback_mode: string;
  agent_session_cost_limit_usd: number;
  agent_request_cost_limit_usd: number;
  cost_limit_scope?: {
    scope: "global" | "project";
    project_id: string;
    session_source: "global" | "project";
    request_source: "global" | "project";
    project_session_cost_limit_usd: number | null;
    project_request_cost_limit_usd: number | null;
  };
  llm_cache_ttl_seconds: number;
  llm_cache_tools_ttl_seconds: number;
  llm_tool_planner_trace_call_enabled: boolean;
  llm_tool_planner_max_tokens: number;
  llm_tool_planner_timeout_seconds: number;
};

export type AdminCorpIdentityColor = {
  token: string;
  hex: string;
  name: string;
};

export type AdminCorpIdentityCategory = {
  name: string;
  count: number;
  examples: string[];
};

export type AdminCorpIdentitySummary = {
  id: string;
  name: string;
  source_file_name: string;
  theme_name: string;
  font_family: string;
  colors: AdminCorpIdentityColor[];
  layout_count: number;
  corporate_safe_layout_count: number;
  recommended_layouts: string[];
  icon_count: number;
  icon_categories: AdminCorpIdentityCategory[];
  profile_root: string;
  office_template_type?: OfficeTemplateType;
  doc_type_label?: string;
};

export type AdminCorpIdentityProfile = {
  id: string;
  name: string;
  profile_root: string;
  created_at: string | null;
  updated_at: string | null;
  summary: AdminCorpIdentitySummary;
  brand_profile_path: string;
  layout_catalog_path: string;
  icon_catalog_path: string;
  guide_path: string;
  is_default: boolean;
  // Optional second upload: an example deck teaching layout usage (Slot 2).
  example_deck_path?: string;
  example_deck_file?: string;
  example_deck_layouts_learned?: number;
  // Token paths the Spec Studio shows read-only.
  studio_locks?: string[];
  // Per-doc-type template lists (multiple per type supported)
  templates: OfficeTemplateEntryMap;
};

export type AdminCorpIdentityListResponse = {
  profiles: AdminCorpIdentityProfile[];
  default_profile_id: string;
};

export type AdminCorpIdentityDetail = AdminCorpIdentityProfile & {
  source_path: string;
  brand_profile: Record<string, unknown>;
  layout_catalog: {
    summary?: {
      total_layouts?: number;
      corporate_safe_count?: number;
      by_category?: Record<string, string[]>;
    };
  };
  icon_catalog: {
    total_icons?: number;
    categories?: Record<string, Array<{ slug: string }>>;
  };
  guide_markdown: string;
};

export type RuntimePanelSection =
  | "priority"
  | "defaults"
  | "routing"
  | "execution"
  | "limits"
  | "fallback"
  | "compression";

export const RUNTIME_PANEL_SECTIONS: Array<{
  id: RuntimePanelSection;
  label: string;
  description: string;
}> = [
  {
    id: "priority",
    label: "Modules & Order",
    description:
      "Keep this view focused on the runtime modules themselves and their fallback order.",
  },
  {
    id: "defaults",
    label: "Defaults",
    description:
      "Backend fallback model and global completion defaults for runtimes.",
  },
  {
    id: "routing",
    label: "Routing",
    description:
      "Review and analyzer models and use-case tag routing.",
  },
  {
    id: "execution",
    label: "Execution",
    description:
      "Choose whether shell and script execution runs on the host or in Docker.",
  },
  {
    id: "limits",
    label: "Limits",
    description:
      "Trace, cache and request-size limits that apply across runtime execution.",
  },
  {
    id: "fallback",
    label: "Fallback",
    description:
      "Decide explicitly what happens when the first runtime in the chain is exhausted.",
  },
  {
    id: "compression",
    label: "Compression",
    description:
      "Compress large connector results before they are sent back into a model.",
  },
];

export type AdminToolResultCompressor = {
  id: string;
  tool_name: string;
  strategy: string;
  config: Record<string, unknown>;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminToolResultCompressionLog = {
  id: string;
  session_id: string;
  tool_name: string;
  compressor_id: string | null;
  strategy: string;
  original_tokens: number;
  compressed_tokens: number;
  compression_ratio: number;
  request_id: string | null;
  created_at: string | null;
};
