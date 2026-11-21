import type { RecentError } from "./connectionsModel";

// A connection's recent errors as people read them. The backend's recent_errors carry fixed codes
// (Knowledge sync reasons, intake run codes) or a health check's own sentence (connections/errors_and_usage.py).
// A known code becomes one sentence; the code itself stays only as a tooltip. Errors older than the last
// successful test are listed under "Earlier".

const SENTENCES: Record<string, string> = {
  // Intakes (secure_work/jira/jira_run_failure.py and the ServiceNow intake).
  jql_invalid: "The ticket filter is not valid JQL.",
  jql_unbalanced: "The ticket filter has unbalanced brackets or quotes.",
  scope_not_allowed: "The token lacks permission for this scope.",
  intake_connection_unavailable: "The intake's connection is no longer available in this workspace.",
  jira_sync_failed: "Fetching tickets from Jira failed.",
  servicenow_connection_not_configured: "The ServiceNow connection is not set up completely.",
  servicenow_endpoint_not_configured: "The ServiceNow table to read is not set up.",
  servicenow_assignment_groups_not_allowed: "The assignment groups are outside what this workspace may read.",
  visible_scopes_unavailable: "The source did not say which projects or spaces the account can see.",
  // Knowledge sync reasons (knowledge/sources/sync).
  acl_unresolved: "Who may read some items could not be determined, so they were held back.",
  confluence_cloud_url_without_wiki: "The Confluence Cloud address must end in /wiki.",
  connection_not_configured: "The connection is not set up completely.",
  connection_not_configured_for_scope: "The connection is not set up for this scope.",
  connection_pin_mismatch: "The source is pinned to a different connection.",
  connection_pin_unknown: "The source is pinned to a connection that no longer exists.",
  source_connection_not_granted: "The connection is not released to this workspace.",
  connector_paused: "The sync is paused.",
  egress_refused: "The platform does not allow requests to this address.",
  evidence_store_not_configured: "The knowledge store is not set up on this platform.",
  listing_stalled: "Listing the source's items stopped making progress.",
  confluence_sync_never_ran: "The sync has never run.",
  confluence_sync_not_configured: "The sync is not set up.",
  own_connection_incomplete: "The workspace's own connection is missing a value.",
  parser_not_configured: "No document reader is set up on this platform.",
  project_deleted: "The workspace was deleted.",
  release_product_ambiguous: "The release matches more than one product.",
  release_product_not_configured: "No product is set for releases.",
  removed_at_source: "The item was removed at the source.",
  repository_too_large: "The repository is too large to read.",
  restricted_acl: "Some items are restricted and were held back.",
  run_in_progress: "Another sync was still running.",
  scheduled_run_failed: "The scheduled sync failed.",
  schedule_owner_not_authorized: "The person who set the schedule may no longer read this source.",
  scope_spans_connections: "The scope reaches across more than one connection.",
  snapshot_upload_required: "A repository snapshot has to be uploaded first.",
  source_contract_violation: "The source answered in an unexpected form.",
  source_not_found: "The source could not be found.",
  source_rate_limited: "The source limited the number of requests.",
  source_unauthorized: "The source refused the credentials.",
  source_unavailable: "The source could not be reached.",
  version_name_unrecognized: "A version name could not be read.",
  version_not_found: "The version could not be found.",
  workspace_inactive: "The workspace is inactive.",
  failed: "The run failed.",
  needs_configuration: "The run needs more setup.",
  // Health checks without their own sentence (connector_health status).
  error: "The connection check failed.",
  degraded: "The connection works only partly.",
  unhealthy: "The connection check failed.",
  timeout: "The connection check timed out.",
};

const CODE = /^([a-z][a-z0-9]*(?:_[a-z0-9]+)*)(?::\s*(.*))?$/s;

export type ErrorLine = { at: string | null; use: string; sentence: string; code: string };

/**
 * One sentence for a recorded error, the code as tooltip. The server's message is the sentence when it is one;
 * a message that is a bare code (e.g. from intake runs) is worded from the table above.
 */
export function errorSentence(message: string, serverCode = ""): { sentence: string; code: string } {
  const text = message.trim();
  if (serverCode) {
    const human = text && !CODE.test(text);
    return { sentence: human ? text : SENTENCES[serverCode] ?? (text && SENTENCES[text]) ?? "The source reported an error.", code: serverCode };
  }
  const match = CODE.exec(text);
  const known = match ? SENTENCES[match[1]] : undefined;
  if (match && known) return { sentence: known, code: text };
  // A single unknown code word: still never shown raw.
  if (match && !match[2] && text.includes("_")) return { sentence: "The source reported an error.", code: text };
  return { sentence: text, code: "" };
}

const USE_LABELS: Record<string, string> = { knowledge: "Knowledge", tickets: "Tickets", access: "Access", agent_tools: "Agent tools" };
export const errorUseLabel = (use: string) => USE_LABELS[use] ?? "Access";

const time = (value: string | null) => (value ? Date.parse(value) : Number.NaN);

/**
 * Errors since the last successful test (shown) and before it (under "Earlier"). Without a successful test
 * everything is recent. A connection whose state is ok and has no newer error shows no count on its tab.
 */
export function splitErrors(errors: RecentError[], lastSuccessAt: string | null): { recent: ErrorLine[]; earlier: ErrorLine[] } {
  const lines = errors.map((error) => ({ at: error.at, use: error.use, ...errorSentence(error.message, error.code) }));
  const cut = time(lastSuccessAt);
  if (Number.isNaN(cut)) return { recent: lines, earlier: [] };
  return {
    recent: lines.filter((line) => !(time(line.at) <= cut)),
    earlier: lines.filter((line) => time(line.at) <= cut),
  };
}

/**
 * The last time the connection was known to work: last_tested_at while its state is ok. A working connection
 * without a test time has worked since its last check, so every recorded error counts as earlier.
 */
export function lastSuccessfulTest(detail: { state: string; lastTestedAt: string | null }): string | null {
  if (detail.state !== "ok") return null;
  return detail.lastTestedAt ?? new Date(8_640_000_000_000_000).toISOString();
}

/** The Errors tab's count: only errors since the last success (none when the connection works and nothing is new). */
export const recentErrorCount = (detail: { state: string; lastTestedAt: string | null; recentErrors: RecentError[] }) =>
  splitErrors(detail.recentErrors, lastSuccessfulTest(detail)).recent.length;
