// Source Sync connector settings read from a listed connector: access mode, connection, schedule and stored config.
import { storedPageTrees } from "./confluencePageTree";
import { REST_KIND } from "./rest/restSourceForm";
import { storedRestBody } from "./rest/restSourceRules";
import { DEFAULT_SCHEDULE_INTERVAL_MINUTES, type AccessMode, type ConnectorConfig, type ConnectorSchedule, type SourceConnector } from "./connectorTypes";

/** The access mode of a Git repository read through a connection; null for any other source. */
export function accessModeOf(connector: SourceConnector): AccessMode | null {
  if (connector.kind !== "git_repository") return null;
  const mode = connector.access_mode ?? connector.scope?.access_mode ?? null;
  return mode === "read_only" || mode === "read_write" ? mode : null;
}

/** Whether a source can carry its own Git token: a Bitbucket Data Center repository read through a connection. */
export function takesGitToken(connector: SourceConnector): boolean {
  return connector.kind === "git_repository" && connector.scope?.host === "bitbucket_datacenter"
    && repositoryConnectionOf(connector) !== null;
}

/** The connection a Git repository is read with; null for a public repository or any other source. */
export function repositoryConnectionOf(connector: SourceConnector): string | null {
  if (connector.kind !== "git_repository") return null;
  const id = connector.connection_id ?? connector.scope?.connection_id ?? null;
  return typeof id === "string" && id ? id : null;
}

export function scheduleOf(connector: SourceConnector): ConnectorSchedule {
  return connector.schedule ?? { enabled: false, interval_minutes: DEFAULT_SCHEDULE_INTERVAL_MINUTES, next_run_at: null };
}

// The stored configuration of a listed connector, for a pause/resume toggle. It carries the schedule unchanged,
// so pausing or resuming never switches a schedule off.
export function configOf(connector: SourceConnector, state = connector.state): ConnectorConfig {
  const schedule = scheduleOf(connector);
  const base = {
    products: connector.products,
    version: connector.version,
    max_items_per_run: connector.max_items_per_run,
    state,
    schedule_enabled: schedule.enabled,
    schedule_interval_minutes: schedule.interval_minutes,
  };
  const { scope } = connector;
  // A pinned connection is carried unchanged, so pausing or resuming never unpins the connector.
  const pin = typeof scope.connection_id === "string" && scope.connection_id ? { connection_id: scope.connection_id } : {};
  if (connector.kind === "servicenow") {
    return {
      ...base,
      ...pin,
      kind: "servicenow",
      knowledge_bases: scope.knowledge_bases ?? [],
      tables: scope.tables ?? [],
      article_query: scope.article_query ?? null,
      record_query: scope.record_query ?? null,
    };
  }
  if (connector.kind === "confluence") {
    // Page trees are carried unchanged, so pausing or resuming never drops them.
    const trees = storedPageTrees(scope);
    return { ...base, ...pin, kind: "confluence", spaces: scope.spaces ?? [], ...(trees.length ? { page_trees: trees } : {}) };
  }
  // Custom REST: the stored scope and mapping unchanged, so pausing or resuming never changes what it reads or who finds it.
  if (connector.kind === REST_KIND) return { ...base, kind: REST_KIND, ...storedRestBody(scope) };
  if (connector.kind === "kubernetes") {
    return { ...base, ...pin, kind: "kubernetes", cluster: scope.cluster ?? "", namespaces: scope.namespaces ?? [] };
  }
  // Only remote_git connectors are reconfigured here: the table offers no toggle for a local snapshot.
  if (connector.kind === "git_repository") {
    // A repository read through a connection is always saved with its connection (the server keeps its access mode).
    const connectionId = repositoryConnectionOf(connector);
    const through = connectionId ? { connection_id: connectionId } : {};
    return {
      ...base,
      ...through,
      kind: "git_repository",
      fetch_mode: "remote_git",
      repository_url: scope.remote ?? "",
      ref: scope.ref ?? "",
      include_globs: scope.include_globs ?? null,
      exclude_globs: scope.exclude_globs ?? null,
      max_files: scope.max_files ?? null,
      max_file_bytes: scope.max_file_bytes ?? null,
    };
  }
  // The releases block is carried unchanged, so pausing or resuming never switches release sync off.
  return { ...base, ...pin, kind: "jira", project_keys: scope.project_keys ?? [], jql: scope.jql ?? null, releases: scope.releases ?? null };
}
