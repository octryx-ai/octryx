// Workspace design artifact, readiness, traceability and trace-sync scheduler types.
import type { SchedulerWorkerApplication } from "../components/taskTypes";

export type AdminDesignArtifactTemplate = {
  artifact_kind: string;
  label: string;
  description: string;
  required_by_default: boolean;
  order_index: number;
};

export type AdminDesignArtifact = {
  id: string;
  project_id: string;
  artifact_kind: string;
  title: string;
  status: string;
  summary: string;
  content_markdown: string;
  owner_user_id?: string | null;
  owner_label?: string | null;
  metadata_json: Record<string, unknown>;
  linked_repository_ids?: string[];
  depends_on_artifact_ids?: string[];
  is_required: boolean;
  order_index: number;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminDesignReadiness = {
  required_total: number;
  approved_required_total: number;
  required_approval_rate: number;
  readiness_score: number;
  missing_required_kinds: string[];
  pending_required_kinds: string[];
  approved_required_kinds: string[];
  blockers: string[];
  artifact_coverage: Record<string, { total: number; approved: number }>;
  repository_traceability: {
    total_repositories: number;
    linked_repositories: number;
    linked_repository_ids: string[];
    coverage_rate: number;
  };
};

export type AdminDesignTraceLink = {
  id: string;
  project_id: string;
  artifact_id: string;
  target_type: string;
  target_id: string | null;
  title: string;
  status: string;
  url: string;
  metadata_json: Record<string, unknown>;
  created_by_user_id?: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminDesignTraceability = {
  total_links: number;
  artifacts_total: number;
  artifacts_linked: number;
  approved_artifacts_total: number;
  approved_artifacts_linked: number;
  approved_trace_rate: number;
  traceability_score: number;
  link_counts_by_type: Record<string, number>;
  blockers: string[];
  task_options: Array<{ id: string; name: string }>;
  items: AdminDesignTraceLink[];
};

export type AdminDesignTraceSyncWorkflow = {
  id: string;
  name: string;
  description: string;
  source_kind: string;
  target_type: string;
  mode: string;
  is_active: boolean;
  providers: string[];
  match_rules: string[];
  limit_per_repository: number;
  template_id?: string;
  is_template?: boolean;
};

export type AdminDesignTraceSyncWorkflowCollection = {
  templates: AdminDesignTraceSyncWorkflow[];
  custom_templates?: AdminDesignTraceSyncWorkflow[];
  items: AdminDesignTraceSyncWorkflow[];
};

export type PanelScheduler = {
  id: string;
  name: string;
  description: string;
  cron_expression: string;
  task_id: string;
  task_name: string;
  is_active: boolean;
  owner_id: string;
  created_at: string;
  /** Optional: an answer without it reads as status not available. */
  worker_application?: SchedulerWorkerApplication | null;
};
