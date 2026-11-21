export type EngineeringKnowledgeSource = {
  id: string;
  source_key: string;
  title: string;
  source_uri: string;
  source_type: string;
  trust_tier: string;
  version_label: string | null;
  checksum: string | null;
  fetch_status: string;
  freshness_status: string;
  raw_archive_path: string | null;
  parsed_archive_path: string | null;
  evidence_archive_path: string | null;
};

export type EngineeringKnowledgeItem = {
  id: string;
  source_id: string | null;
  item_key: string;
  title: string;
  summary: string;
  content?: string;
  content_preview: string;
  tags: string[];
  triggers: string[];
  version_scope: Record<string, unknown>;
  retrieval_priority: string;
  retrieval_rank: number;
  metadata: Record<string, unknown>;
  evidence?: Array<Record<string, unknown>>;
  evidence_status?: string;
};

export type EngineeringKnowledgePackAssignment = {
  id: string;
  scope_type: string;
  scope_id: string | null;
  workspace_id: string | null;
  repository_id: string | null;
  stack_key: string;
  assignment_status: string;
  priority: number;
  assignment_policy: Record<string, unknown>;
};

export type EngineeringKnowledgeManifest = {
  schema_version?: number;
  manifest_kind?: string;
  pack?: Record<string, unknown>;
  sources?: unknown[];
  items?: unknown[];
  quality_inputs?: Record<string, unknown>;
  export?: {
    format?: string;
    export_ready?: boolean;
    contains_archive_paths?: boolean;
    requires_archive_root?: boolean;
  };
};

export type EngineeringKnowledgePackVersion = {
  id: string;
  version: number;
  status: string;
  source_versions: Record<string, string>;
  target_versions: Record<string, string>;
  compatibility_facts: Record<string, unknown>;
  manifest: EngineeringKnowledgeManifest;
  archive_root: string | null;
  quality_status: string;
  quality_report: Record<string, unknown>;
  source_count: number;
  item_count: number;
  item_evidence_count?: number;
  assignment_count: number;
  active_assignment_count: number;
  published_at: string | null;
  sources?: EngineeringKnowledgeSource[];
  items?: EngineeringKnowledgeItem[];
  assignments?: EngineeringKnowledgePackAssignment[];
};

export type EngineeringKnowledgePack = {
  id: string;
  key: string;
  name: string;
  description: string;
  stack_key: string;
  lifecycle_status: string;
  is_active: boolean;
  source_policy: Record<string, unknown>;
  freshness_policy: Record<string, unknown>;
  retrieval_policy: Record<string, unknown>;
  toolchain_policy: Record<string, unknown>;
  resolution_policy: Record<string, unknown>;
  latest_published_version_id: string | null;
  versions: EngineeringKnowledgePackVersion[];
};

export type EngineeringKnowledgeBuildRun = {
  id: string;
  pack_id: string | null;
  pack_version_id: string | null;
  pack_key: string | null;
  pack_version: number | null;
  trigger: string;
  prompt: string;
  stack_key: string | null;
  source_versions: Record<string, string>;
  target_versions: Record<string, string>;
  status: string;
  source_plan: Record<string, unknown>;
  quality_report: Record<string, unknown>;
  publish_decision: string;
  approval_status: string;
  blocker_details: Array<{ code?: string; message?: string }>;
  started_at: string | null;
  completed_at: string | null;
};

export type EngineeringKnowledgeRetrievalRecord = {
  record_id: string;
  record_kind: string;
  record_key: string;
  title: string;
  summary: string;
  content: string;
  pack_id: string;
  pack_version_id: string;
  stack_key: string;
  source_versions: Record<string, string>;
  target_versions: Record<string, string>;
  coverage_areas: string[];
  tags: string[];
  triggers: string[];
  source_key: string | null;
  source_uri: string | null;
  source_type: string | null;
  trust_tier: string | null;
  freshness_status: string | null;
  archive_path: string | null;
  canonical_uri: string | null;
  fact_id: string | null;
  metadata: Record<string, unknown>;
};

export type EngineeringKnowledgeRetrievalSearchPayload = {
  status: string;
  count: number;
  records: EngineeringKnowledgeRetrievalRecord[];
};
