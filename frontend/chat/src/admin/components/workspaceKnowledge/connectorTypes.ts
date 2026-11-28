import type { ReleasesBlock, ReleaseSyncState } from "./jiraReleasesContract";
import type { PageTree } from "./confluencePageTree";

export type ConnectorKind = "confluence" | "jira" | "servicenow" | "git_repository" | "kubernetes" | "custom_rest";
export type RunState = "running" | "completed" | "budget_exhausted" | "failed" | "needs_configuration";
export type OutcomeKind = "created" | "updated" | "unchanged" | "retired" | "skipped" | "failed" | "deferred";
export type RunMode = "full" | "incremental" | "incremental_fallback";

export type RunReport = Partial<Record<OutcomeKind | "listed" | "outcomes_recorded", number>> & {
  skipped_reasons?: Record<string, number>;
  repository?: { ref: string; commit: string };
  mode?: RunMode;
  pass_completed?: boolean;
  withheld?: number;
  withheld_reasons?: Record<string, number>;
  acl_enforced?: boolean;
};

export type ItemOutcome = {
  external_id: string | null;
  // Never set for a withheld item: the report is readable by every Workspace member.
  title: string | null;
  outcome: OutcomeKind;
  reason: string | null;
};

export type SyncRun = {
  id: string;
  state: RunState;
  reason: string | null;
  report: RunReport;
  started_at: string | null;
  finished_at: string | null;
  outcomes?: ItemOutcome[];
};

export type SyncCursor = {
  pass_number: number;
  token: string | null;
  pass_started_at: string | null;
  last_completed_at: string | null;
  completed_passes: number;
  last_pass_closed_at?: string | null;
  last_pass_failures?: number | null;
};

export const MIN_SCHEDULE_INTERVAL_MINUTES = 15;
export const MAX_SCHEDULE_INTERVAL_MINUTES = 7 * 24 * 60;
export const DEFAULT_SCHEDULE_INTERVAL_MINUTES = 360;

export type ConnectorSchedule = { enabled: boolean; interval_minutes: number; next_run_at: string | null };

export type GitFetchMode = "remote_git" | "local_snapshot";
export type AccessMode = "read_only" | "read_write";

export const ACCESS_MODE_LABEL: Record<AccessMode, string> = { read_only: "Read only", read_write: "Read & write" };

export type ConnectorScope = {
  spaces?: string[];
  page_trees?: PageTree[];
  project_keys?: string[];
  jql?: string | null;
  knowledge_bases?: string[];
  tables?: string[];
  article_query?: string | null;
  record_query?: string | null;
  releases?: ReleasesBlock;
  connection_id?: string;
  cluster?: string;
  namespaces?: string[];
  fetch_mode?: GitFetchMode;
  remote?: string;
  web_base?: string | null;
  ref?: string | null;
  head_commit?: string;
  head_dirty?: boolean;
  head_pushed?: boolean;
  include_globs?: string[];
  exclude_globs?: string[];
  max_files?: number | null;
  max_file_bytes?: number | null;
  access_mode?: AccessMode | null;
} & Record<string, unknown>;

export type SourceConnector = {
  connector_key: string;
  // A string: a newer backend may list kinds this UI cannot configure yet.
  kind: string;
  scope: ConnectorScope;
  products: string[];
  version: string | null;
  max_items_per_run: number;
  state: "active" | "paused";
  cursor: SyncCursor;
  schedule?: ConnectorSchedule;
  running: boolean;
  last_run: SyncRun | null;
  served_items?: number;
  release_sync?: ReleaseSyncState;
  access_mode?: AccessMode | null;
  connection_id?: string | null;
  connection_candidates?: { id: string; name: string; type: string }[];
  git_token?: GitTokenState;
  acl?: { visibility?: string; acl_enforced?: boolean; restricted_items_withheld?: boolean; note?: string | null };
};

export type GitTokenState = { configured: boolean; set_at?: string | null; set_by?: string | null };

export type ConnectorConfig = {
  kind: ConnectorKind;
  spaces?: string[];
  page_trees?: PageTree[];
  project_keys?: string[];
  jql?: string | null;
  knowledge_bases?: string[];
  tables?: string[];
  article_query?: string | null;
  record_query?: string | null;
  fetch_mode?: "remote_git";
  repository_url?: string;
  ref?: string;
  include_globs?: string[] | null;
  exclude_globs?: string[] | null;
  max_files?: number | null;
  max_file_bytes?: number | null;
  cluster?: string;
  namespaces?: string[];
  products: string[];
  version: string | null;
  max_items_per_run: number;
  state: "active" | "paused";
  // The server reads a missing flag as "off", so a save must carry the current schedule.
  schedule_enabled: boolean;
  schedule_interval_minutes: number;
  // The PUT replaces the whole configuration, so every save carries the current block (null switches release sync off).
  releases?: ReleasesBlock | null;
  connection_id?: string | null;
  // Omitted on a re-save so the server keeps the stored mode.
  access_mode?: AccessMode;
  // Omitted on a re-save so the server keeps the stored token.
  git_token?: string;
  scope?: Record<string, unknown>;
  mapping?: Record<string, unknown>;
};

export type ConnectionRepositoryConfig = Partial<ConnectorConfig> & {
  kind: "git_repository";
  fetch_mode: "remote_git";
  repository_url: string;
  ref: string;
  connection_id: string;
  access_mode: AccessMode;
};
