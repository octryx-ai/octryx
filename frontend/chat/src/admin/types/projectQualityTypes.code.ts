// Workspace code repository, code index run and code graph run types.
export type AdminCodeIndexRun = {
  id: string;
  status: string;
  trigger: string;
  index_backend: string;
  semantic_backend: string;
  structure_backend: string;
  graph_backend: string;
  files_indexed: number;
  symbols_indexed: number;
  references_indexed: number;
  duration_ms: number | null;
  storage_path: string | null;
  languages_json: Record<string, number>;
  summary_json: Record<string, unknown>;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
};

export type AdminCodeRepository = {
  id: string;
  project_id: string | null;
  name: string;
  description: string;
  repo_root: string;
  provider: string;
  remote_url: string | null;
  default_branch: string | null;
  index_backend: string;
  semantic_backend: string;
  structure_backend: string;
  graph_backend: string;
  config_json: Record<string, unknown>;
  capabilities_json: Record<string, unknown>;
  effective_backends?: Record<string, string>;
  backend_status?: Record<
    string,
    {
      configured: string;
      effective: string;
      available: boolean;
      ready: boolean;
      artifact_status: string | null;
      mode: string;
      detail: string;
    }
  >;
  code_graph_status?: {
    status: string;
    repository_id: string;
    project_id: string | null;
    graph_repository_id: string | null;
    backend: string | null;
    schema_version: string | null;
    indexing_mode: string | null;
    staleness_state: string;
    capabilities: Record<string, unknown>;
    latest_run: AdminCodeGraphRun | null;
    run_history: AdminCodeGraphRun[];
    summary: {
      file_count: number;
      node_count: number;
      edge_count: number;
      symbol_count: number;
      reference_count: number;
      route_count: number;
      chunk_count: number;
      unresolved_reference_count: number;
      language_distribution: Record<string, number>;
    };
    sync: {
      state: string;
      warnings: Array<Record<string, unknown>>;
      summary: Record<string, unknown>;
    };
    stale_files: Array<{
      file_path: string;
      status: string;
      reason: string;
      source: string;
      checked_at: string | null;
    }>;
    parse_errors: Array<{
      file_path: string;
      language: string;
      parse_error: string;
      is_current: boolean;
    }>;
    metrics: {
      latest_duration_ms: number | null;
      latest_file_count: number;
      latest_node_count: number;
      latest_edge_count: number;
      latest_unresolved_reference_count: number;
      stale_file_count: number;
      parse_error_count: number;
    };
  };
  latest_index_summary: Record<string, unknown>;
  last_index_status: string | null;
  last_indexed_at: string | null;
  last_index_error: string | null;
  is_active: boolean;
  index_runs: AdminCodeIndexRun[];
  created_at: string | null;
  updated_at: string | null;
};

export type AdminCodeGraphRun = {
  id: string;
  repository_id: string;
  graph_repository_id: string;
  status: string;
  trigger: string;
  backend: string;
  file_count: number;
  node_count: number;
  edge_count: number;
  unresolved_reference_count: number;
  duration_ms: number | null;
  is_stale: boolean;
  staleness_reason: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
};
