import { RELEASE_CODE_TEXT } from "./jiraReleasesContract";
import { PAGE_TREE_REASON_TEXT } from "./confluencePageTree";
import { restReasonText } from "./rest/restSourceRefusals";

export class ConnectorRequestError extends Error {
  readonly reason: string | null;
  readonly field: string | null;
  readonly status: number;
  // Visibility goes downward only: a Workspace admin sees a platform connection's name, not its id.
  readonly connectionId: string | null;
  readonly connectionName: string | null;

  constructor(message: string, reason: string | null, field: string | null = null, status = 0,
    connection: { id?: string | null; name?: string | null } = {}) {
    super(message);
    this.reason = reason;
    this.field = field;
    this.status = status;
    this.connectionId = connection.id ?? null;
    this.connectionName = connection.name ?? null;
  }
}

export const NOT_GRANTED = "source_connection_not_granted";

export const connectionAdminHref = (connectionId: string) =>
  `/chat?area=admin&tab=adminConnections&connection=${encodeURIComponent(connectionId)}`;

export function notGrantedView(error: unknown): { text: string; href: string | null } | null {
  if (!(error instanceof ConnectorRequestError) || error.reason !== NOT_GRANTED) return null;
  const which = error.connectionName ? `The connection “${error.connectionName}”` : "This connection";
  if (error.connectionId) {
    return { text: `${which} is not released to this Workspace. Release it in Admin › Connections: tick this Workspace under Workspaces.`,
      href: connectionAdminHref(error.connectionId) };
  }
  return { text: `${which} is not released to this Workspace. A platform admin must release the connection for this Workspace.`, href: null };
}

// Unknown reasons fall back to the code itself.
const REASON_TEXT: Record<string, string> = {
  restricted_acl: "withheld: restricted in the source system",
  acl_unresolved: "failed: who may read it could not be determined",
  removed_at_source: "removed in the source system",
  source_unauthorized: "the source system rejected the connection's credential",
  source_not_found: "not found in the source system",
  source_rate_limited: "the source system rate-limited the request; run again later",
  source_unavailable: "the source system is unavailable",
  source_contract_violation: "the source system answered in an unexpected format",
  listing_stalled: "the source listing did not advance",
  connection_not_available: "the connection is not available to this Workspace",
  source_connection_not_granted:
    "this connection is not released to this Workspace: a platform admin releases it in Admin › Connections (open the connection, tick this Workspace under Workspaces)",
  connection_disabled: "the connection is disabled",
  connection_use_disabled: "using this connection is switched off",
  repository_not_on_connection_host: "the repository is not on the connection's host",
  connection_choice_required: "several connections can read this repository: choose one in the source's settings (Edit › Read through connection)",
  git_token_invalid: "Bitbucket rejected the Git access token (unknown, expired or revoked)",
  git_token_wrong_repository: "the Git access token does not reach this repository: create it on this repository or its project",
  git_token_not_supported: "a Git access token applies only to a Bitbucket Data Center repository added from a connection",
  own_connection_incomplete:
    "this Workspace's own connection is incomplete: set its URL, auth mode and credential (Workspace settings → Connectors), or use the global connection",
  connection_not_configured:
    "no active connection: configure the Workspace's Confluence, Jira or ServiceNow connector (URL and credential) first",
  parser_not_configured: "the document parser sandbox is not configured, so pages cannot be ingested",
  connection_not_configured_for_scope:
    "no connection serves this space, project or table: bind it to a named connection or allow it on the default connection",
  scope_spans_connections:
    "the projects or tables are served by different connections: configure one connector per connection",
  connection_pin_mismatch:
    "the connector is pinned to a connection that does not serve all its spaces, projects or tables (or no longer exists): pin it to the serving connection or clear the pin",
  connection_pin_unknown:
    "the pinned connection is not a connection of this connector this Workspace can use: pick one from the list or clear the pin",
  scope_not_allowed:
    "a space (or a page tree's space), project or table is outside the connection's allowed spaces, projects or tables",
  egress_refused:
    "outbound connection refused by the egress policy (egress_refused): the connection's host is not public, so no request was sent",
  run_in_progress: "a run of this connector is already in progress",
  connector_paused: "the connector is paused; resume it to run",
  workspace_inactive: "the Workspace is deleted or archived, so its connectors cannot be configured or run",
  invalid_request: "the ingestion refused the item",
  unsupported_media_type: "the item's content type is not supported",
  needs_configuration: "knowledge storage is not configured",
  unavailable: "knowledge storage is unavailable",
  limit_exceeded: "the item is larger than the size limit",
  contract_violation: "a knowledge dependency failed",
  denied: "access denied",
  not_found: "not found",
  repository_too_large: "repository exceeds the configured file or size limits",
  repository_empty: "empty repository — ready for a first commit; there is nothing to sync yet",
  snapshot_upload_required: "files arrive with a launcher upload",
  path_too_long: "skipped: the file path is too long",
  excluded: "excluded by the include or exclude globs",
  skipped_binary: "skipped: binary file",
  skipped_too_large: "skipped: larger than the per-file size limit",
  skipped_unsupported_path: "skipped: the file path is not supported",
  skipped_empty: "skipped: the file is empty",
  ...RELEASE_CODE_TEXT,
  ...PAGE_TREE_REASON_TEXT,
};

export function reasonText(reason: string | null | undefined): string {
  if (!reason) return "";
  if (REASON_TEXT[reason]) return REASON_TEXT[reason];
  return reason.startsWith("custom_rest_") || reason.startsWith("rest_source_") ? restReasonText(reason) : reason.replace(/_/g, " ");
}
