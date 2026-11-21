// Work workflow definitions, state transitions and their events.

export type WorkWorkflowState = {
  key: string;
  label: string;
  description?: string;
};

export type WorkWorkflowMapping = {
  // The source-neutral names (backend `sync_policy`), the same for every source.
  source_status?: string | null;
  source_transition?: string | null;
  comment_template?: string;
  labels?: string[];
  custom_fields?: Record<string, unknown>;
  sync_back?: boolean;
};

export type WorkWorkflowDefinition = {
  id: string;
  name: string;
  description?: string;
  project_id?: string | null;
  states: WorkWorkflowState[];
  mappings: Record<string, WorkWorkflowMapping>;
  sync_policy: Record<string, unknown>;
  is_default: boolean;
  is_active: boolean;
  updated_at?: string | null;
};

export type WorkTransitionPreview = {
  valid: boolean;
  error?: string | null;
  workflow_id: string;
  work_item_id: string;
  source_key: string;
  from_state: string;
  to_state: string;
  reason: string;
  jira_sync_preview: {
    mode: string;
    will_mutate_jira: boolean;
    target_status?: string | null;
    transition?: string | null;
    comment_template?: string;
    labels?: string[];
    custom_fields?: Record<string, unknown>;
    sync_back?: boolean;
    local_only?: boolean;
    // Exactly what an apply writes to Jira.
    effects: { kind: "status" | "comment" | "labels" | string; value: unknown }[];
    // Binds an apply to this preview; the apply sends them back (409 preview_stale).
    effects_hash?: string | null;
    workflow_updated_at?: string | null;
    // After an apply: what the tracker driver did.
    execution?: Record<string, unknown>;
    // What Jira really offers for the issue, and why an apply would be refused.
    transition_available?: boolean | null;
    offered_transitions?: { name?: string | null; to?: string | null }[];
    blocked_reason?: string | null;
  };
  conflict: {
    has_conflict: boolean;
    reason?: string | null;
    last_source_updated_at?: string | null;
    source_jira_updated_at?: string | null;
  };
};

export type WorkStateEvent = {
  id: string;
  work_item_id: string;
  workflow_id?: string | null;
  from_state?: string | null;
  to_state: string;
  actor_id: string;
  reason?: string;
  source: string;
  dry_run: boolean;
  jira_sync_preview: WorkTransitionPreview["jira_sync_preview"];
  conflict: WorkTransitionPreview["conflict"];
  created_at?: string | null;
};
