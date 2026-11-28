export type AgentModeOptionRow = {
  id?: string;
  key: string;
  name: string;
};

export type PanelTaskRow = {
  id: string;
  name: string;
  description: string;
  task_type: string;
  agent_type: string;
  is_active: boolean;
  config?: Record<string, unknown>;
  run_count: number;
  running_count: number;
  queued_count?: number;
  last_run_status: string | null;
  last_run_at: string | null;
  created_at?: string;
  max_concurrent_agents?: number;
  default_runtime_selector?: Record<string, unknown>;
  recent_runs?: PanelTaskRunRow[];
  step_count?: number;
  dependency_count?: number;
  dependent_count?: number;
  next_queue_priority?: number | null;
  /** The Action's Workspace; when absent the guided form edits on the advanced path. */
  project_id?: string | null;
  /** "task_definition", "agent_definition" or "workflow_run"; describes the current setting, never past runs. */
  dispatch_binding?: string | null;
  /** The schedulers and inbound webhooks that start this Action. */
  started_by?: { kind: string; name: string; when: string; active: string }[];
  /** A Work-intake job, owned by Work → Intake (read-only here). */
  managed_by_work?: boolean;
};

export type PanelTaskDependencyRow = {
  id: string;
  task_id: string;
  depends_on_task_id: string;
  condition: string;
  task_name: string;
  depends_on_task_name: string;
};

export type PanelTaskDependencyStateRow = {
  dependencies: PanelTaskDependencyRow[];
  dependents: PanelTaskDependencyRow[];
  available_tasks: { id: string; name: string }[];
};

export type StepLogEntryRow = {
  step_id: string;
  position: number;
  name: string;
  step_type: string;
  status: string;
  error: string | null;
  fix_attempts: number;
  session_ids: string[];
  output_keys: string[];
};

export type PanelTaskRunRow = {
  id: string;
  task_id: string;
  session_id: string | null;
  status: string;
  started_by: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  duration_seconds: number | null;
  steps_log: StepLogEntryRow[];
  queue_priority?: number | null;
  queue_status?: string | null;
  queue_required_domain?: string | null;
  queue_assigned_to?: string | null;
  /** A fixed dispatcher code while the run is still queued, else null (never raw errors). */
  queue_wait_reason?: string | null;
  queued_at?: string | null;
  queue_started_at?: string | null;
  estimated_wait_seconds?: number | null;
};

export type PanelTaskStepRow = {
  id: string;
  task_id: string;
  position: number;
  name: string;
  step_type: string;
  connector: string | null;
  connector_action: string | null;
  connector_params: Record<string, unknown>;
  instructions: string;
  runtime_selector: { runtime_target_id?: string };
  context_fields: string[];
  allowed_tools?: string[];
  spawn_strategy?: string;
  spawn_count?: number | null;
  max_fix_attempts: number;
  condition_expr?: string;
  condition_true_step?: number | null;
  condition_false_step?: number | null;
  agent_timeout_seconds: number;
  is_enabled: boolean;
};

export type PanelAgentRow = {
  id: string;
  name: string;
  isActive?: boolean;
  /** "" (agent list) or null (agent catalog) for a global agent; anything else names a workspace. */
  projectId?: string | null;
  /** The agent's permission-mode key. */
  agentType?: string;
  goal?: string;
  systemPrompt?: string;
  outputPrompt?: string;
  steps?: { instructions?: string; isEnabled?: boolean }[];
  /** The agent's checked output format as the panel reports it; read with agentReplyFormat. */
  replyContract?: unknown;
  /** The platform agent key ("assistant" | "engineer" | "reviewer"), "" for any other agent. */
  builtinKey?: string;
};

/** Worker registration state of a scheduler; describes registration, never a run. */
export type SchedulerWorkerApplication = {
  status: "paused" | "pending" | "applied" | "worker_unavailable" | "invalid_schedule";
  next_run_at: string | null;
  timezone: string | null;
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
  schedule_words?: string;
  next_run?: string | null;
  last_run?: { status: string; at: string | null } | null;
  workspace_name?: string;
  managed_by_work?: boolean;
  read_only?: boolean;
};
