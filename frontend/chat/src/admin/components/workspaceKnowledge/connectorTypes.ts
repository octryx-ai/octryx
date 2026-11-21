// Source Sync connector types: runs, cursors, schedules, scopes, listed connectors and the configuration sent.
import type { ReleasesBlock, ReleaseSyncState } from "./jiraReleasesContract";
import type { PageTree } from "./confluencePageTree";

export type ConnectorKind = "confluence" | "jira" | "servicenow" | "git_repository" | "kubernetes" | "custom_rest";
export type RunState = "running" | "completed" | "budget_exhausted" | "failed" | "needs_configuration";
// `deferred`: a scheduled run listed the item but left its fetch for the next run.
export type OutcomeKind = "created" | "updated" | "unchanged" | "retired" | "skipped" | "failed" | "deferred";
export type RunMode = "full" | "incremental" | "incremental_fallback";

export type RunReport = Partial<Record<OutcomeKind | "listed" | "outcomes_recorded", number>> & {
  // Why items were skipped, by fixed reason (restricted_acl, excluded, skipped_binary, ...); any kind may report it.
  skipped_reasons?: Record<string, number>;
  // Git repository only: the requested ref and the commit it resolved to for this run.
  repository?: { ref: string; commit: string };
  // Freshness facts, each optional: how the run listed the source, whether it completed
  // a listing pass, the connector's current withheld items (total and by reason) and whether the Workspace
  // enforces source permissions.
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
  // Optional: when the last listing pass closed and how many of its items failed
  // or were deferred. A pass with failures does not move last_completed_at.
  last_pass_closed_at?: string | null;
  last_pass_failures?: number | null;
};

// The server's schedule bounds (sync/config.py): never more often than every 15 minutes, at most every 7 days.
export const MIN_SCHEDULE_INTERVAL_MINUTES = 15;
export const MAX_SCHEDULE_INTERVAL_MINUTES = 7 * 24 * 60;
export const DEFAULT_SCHEDULE_INTERVAL_MINUTES = 360;

export type ConnectorSchedule = { enabled: boolean; interval_minutes: number; next_run_at: string | null };

export type GitFetchMode = "remote_git" | "local_snapshot";
// A Git repository read through a named connection (Bitbucket): read_write also lets agents push, branch and open pull
// requests on it through that connection.
export type AccessMode = "read_only" | "read_write";

export const ACCESS_MODE_LABEL: Record<AccessMode, string> = { read_only: "Read only", read_write: "Read & write" };

export type ConnectorScope = {
  spaces?: string[];
  // Confluence only: root pages synced with every page below them; absent when none are set.
  page_trees?: PageTree[];
  project_keys?: string[];
  jql?: string | null;
  knowledge_bases?: string[];
  tables?: string[];
  article_query?: string | null;
  record_query?: string | null;
  // Jira only: absent means release sync is off.
  releases?: ReleasesBlock;
  // The named connection this connector is pinned to (absent: each item uses the connection that binds it).
  connection_id?: string;
  // Kubernetes only: the cluster (its named connection's binding) and the namespaces read (empty: all allowed).
  cluster?: string;
  namespaces?: string[];
  // Git repository only. A remote_git connector fetches `remote` (its repository URL) at `ref`; a local_snapshot
  // connector is created and fed by a launcher upload and is read-only here. head_* is run state: the commit of the
  // last completed pass, absent before one.
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
  // Git repository through a connection only: how agents may use the repository.
  access_mode?: AccessMode | null;
} & Record<string, unknown>;

export type SourceConnector = {
  connector_key: string;
  // A string, not ConnectorKind: a newer backend may list kinds this UI cannot configure yet.
  kind: string;
  scope: ConnectorScope;
  products: string[];
  version: string | null;
  max_items_per_run: number;
  state: "active" | "paused";
  cursor: SyncCursor;
  // Optional; a missing block is read as "off".
  schedule?: ConnectorSchedule;
  running: boolean;
  last_run: SyncRun | null;
  // The items it serves to search now (synced runs and launcher snapshots alike); optional.
  served_items?: number;
  // Jira only.
  release_sync?: ReleaseSyncState;
  // Git repository only: the connection it is read with and its access mode; null for a
  // public repository.
  access_mode?: AccessMode | null;
  connection_id?: string | null;
  // Git repository linked to no connection: the connections that could read it; absent once linked.
  connection_candidates?: { id: string; name: string; type: string }[];
  // Git repository only: whether the repository has its own Git token (a Bitbucket Data
  // Center HTTP access token, used for Git over HTTPS instead of the connection's sign-in). Never the token itself.
  git_token?: GitTokenState;
  // Custom REST only: visibility, whether the Workspace enforces source ACLs, and whether restricted items are
  // therefore withheld (with the server's note).
  acl?: { visibility?: string; acl_enforced?: boolean; restricted_items_withheld?: boolean; note?: string | null };
};

export type GitTokenState = { configured: boolean; set_at?: string | null; set_by?: string | null };

export type ConnectorConfig = {
  kind: ConnectorKind;
  spaces?: string[];
  // Confluence only; omitted when the connector syncs whole spaces only.
  page_trees?: PageTree[];
  project_keys?: string[];
  jql?: string | null;
  knowledge_bases?: string[];
  tables?: string[];
  article_query?: string | null;
  record_query?: string | null;
  // Git repository only; null limits and globs leave the server defaults. remote_git is the only mode the UI
  // configures: local_snapshot connectors come from the launcher.
  fetch_mode?: "remote_git";
  repository_url?: string;
  ref?: string;
  include_globs?: string[] | null;
  exclude_globs?: string[] | null;
  max_files?: number | null;
  max_file_bytes?: number | null;
  // Kubernetes only.
  cluster?: string;
  namespaces?: string[];
  products: string[];
  version: string | null;
  max_items_per_run: number;
  state: "active" | "paused";
  // Always sent: the server reads a missing flag as "off", so a save must carry the current schedule.
  schedule_enabled: boolean;
  schedule_interval_minutes: number;
  // Jira only. The PUT replaces the whole configuration: a missing block switches release sync off, so every save
  // of a Jira connector carries its current block (or null to switch it off on purpose).
  releases?: ReleasesBlock | null;
  // Confluence, Jira, ServiceNow, Kubernetes: read only with this named connection (id or "default"); null: by binding.
  // Git repository: the connection the repository is read with (absent for a public repository); every save of such a
  // source sends it.
  connection_id?: string | null;
  // Git repository through a connection only; omitted on a re-save, so the server keeps the stored mode.
  access_mode?: AccessMode;
  // Bitbucket Data Center repository through a connection only: its own Git token, checked against exactly that
  // repository and stored encrypted; omitted on a re-save, so the server keeps the stored token.
  git_token?: string;
  // Custom REST only: the generic configuration objects (sync/rest_config.py); every save sends both.
  scope?: Record<string, unknown>;
  mapping?: Record<string, unknown>;
};

// A Git repository added from a connection: the repository, its ref, the connection and the access mode; every other
// field is optional (the server applies its defaults for a new source; an existing one sends its stored values).
export type ConnectionRepositoryConfig = Partial<ConnectorConfig> & {
  kind: "git_repository";
  fetch_mode: "remote_git";
  repository_url: string;
  ref: string;
  connection_id: string;
  access_mode: AccessMode;
};
