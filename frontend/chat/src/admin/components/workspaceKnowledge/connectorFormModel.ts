import { splitProducts } from "./workspaceKnowledgeRequest";
import { DEFAULT_SCHEDULE_INTERVAL_MINUTES, MAX_SCHEDULE_INTERVAL_MINUTES, MIN_SCHEDULE_INTERVAL_MINUTES } from "./connectorTypes";
import { repositoryConnectionOf, scheduleOf } from "./connectorConfig";
import type { ConnectorConfig, ConnectorKind, SourceConnector } from "./connectorTypes";
import type { ReleasesBlock } from "./jiraReleasesContract";
import { EMPTY_GIT_FIELDS, gitFieldsFromScope, gitRepositoryScope } from "./gitRepositoryScope";
import type { GitRepositoryFields } from "./gitRepositoryScope";
import { SPACE_KEY, pageTreesProblem, storedPageTrees } from "./confluencePageTree";
import type { PageTree } from "./confluencePageTree";
import { REST_KIND, emptyRestKnowledgeForm, restKnowledgeFormOf } from "./rest/restSourceForm";
import { restKnowledgeBody, restKnowledgeProblems } from "./rest/restSourceRules";
import type { RestKnowledgeForm } from "./rest/restSourceForm";

export type ServiceNowTable = "incident" | "problem";
export const SERVICENOW_TABLES: ServiceNowTable[] = ["incident", "problem"];

// The kinds this form configures, in selector order.
export const CONNECTOR_KINDS: ConnectorKind[] = ["confluence", "jira", "servicenow", "git_repository", "kubernetes", "custom_rest"];

export type FormState = GitRepositoryFields & {
  key: string;
  kind: ConnectorKind;
  // Confluence space keys or Jira project keys. The Git repository fields come from GitRepositoryFields.
  keys: string;
  // Confluence: whole spaces, or page trees (a root page and every page below it; whole spaces may be kept too).
  scopeMode: "spaces" | "trees";
  pageTrees: PageTree[];
  jql: string;
  // ServiceNow: knowledge base sys_ids, record tables, and the two optional encoded queries.
  knowledgeBases: string;
  tables: ServiceNowTable[];
  articleQuery: string;
  recordQuery: string;
  products: string;
  version: string;
  limit: string;
  state: "active" | "paused";
  scheduleEnabled: boolean;
  scheduleInterval: string;
  // A Jira connector's stored releases block, carried unchanged (it is edited in its own drawer); null when off.
  releases: ReleasesBlock | null;
  // Confluence, Jira, ServiceNow: the named connection (its id, or "default") this connector reads with;
  // empty: each space, project or table uses the connection that binds it.
  connectionId: string;
  // Kubernetes: the cluster (bound by a named connection) and optional namespaces, comma separated.
  cluster: string;
  namespaces: string;
  // Custom REST: the definition, operations, content, mapping, role and visibility (rest/restSourceModel.ts).
  rest: RestKnowledgeForm;
};

const CONNECTOR_KEY = /^[a-z0-9][a-z0-9-]{0,39}$/;
const PROJECT_KEY = /^[A-Z][A-Z0-9_]{0,49}$/;
const PRODUCT = /^[a-z0-9][a-z0-9-]{0,39}$/;
const VERSION = /^[0-9A-Za-z][0-9A-Za-z._+-]{0,39}$/;
const ORDER_BY = /\border\s+by\b/i;
const SYS_ID = /^[0-9a-f]{32}$/;
const CONNECTION_ID = /^[A-Za-z0-9_-]{1,36}$/;
const PINNABLE: readonly ConnectorKind[] = ["confluence", "jira", "servicenow", "kubernetes"];
// The server's Kubernetes scope rules (sync/kubernetes_connection.py, sync/config.py).
const CLUSTER = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$/;
const NAMESPACE = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/;
const MAX_NAMESPACES = 50;

/** Whether a connector of this kind can be pinned to one named connection by id. */
export function pinnable(kind: ConnectorKind): boolean {
  return PINNABLE.includes(kind);
}
// Every encoded-query segment starts with a (lowercase) field name, or with OR and a field name; see
// servicenow_scope.validate_encoded_query.
const CONDITION = /^[a-z][a-z0-9_.]*/;
const OR_CONDITION = /^OR[a-z][a-z0-9_.]*/;
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;
const MAX_SCOPE_KEYS = 20;
const MAX_QUERY_CHARS = 500;
// A Confluence page or space address: Cloud https://<site>.atlassian.net/wiki/spaces/KEY/..., Server/DC .../spaces/KEY.
const SPACE_IN_URL = /\/spaces\/(~?[A-Za-z0-9_]{1,64})(?:[/?#]|$)/;

// The schedule offered as presets; any other stored interval stays editable as "custom".
export const SCHEDULE_PRESETS: { minutes: number; label: string }[] = [
  { minutes: 15, label: "Every 15 minutes" },
  { minutes: 60, label: "Every hour" },
  { minutes: 360, label: "Every 6 hours" },
  { minutes: 1440, label: "Daily" },
];

/** The preset matching an interval text, or "custom" for any other value (kept as typed, never rounded). */
export function schedulePresetOf(interval: string): string {
  const minutes = Number(interval);
  return SCHEDULE_PRESETS.some((preset) => preset.minutes === minutes) ? String(minutes) : "custom";
}

/** The space key inside a pasted Confluence address, or null. Only used to explain a refusal, never to rewrite. */
export function spaceKeyFromUrl(value: string): string | null {
  if (!/^https?:\/\//i.test(value.trim())) return null;
  return SPACE_IN_URL.exec(value.trim())?.[1] ?? null;
}

export function initialForm(connector: SourceConnector | null): FormState {
  const empty: FormState = {
    key: "", kind: "confluence", keys: "", scopeMode: "spaces", pageTrees: [], jql: "", knowledgeBases: "", tables: [], articleQuery: "", recordQuery: "",
    products: "", version: "", limit: "100", state: "active",
    scheduleEnabled: false, scheduleInterval: String(DEFAULT_SCHEDULE_INTERVAL_MINUTES), releases: null,
    connectionId: "", cluster: "", namespaces: "", rest: emptyRestKnowledgeForm(), ...EMPTY_GIT_FIELDS,
  };
  if (!connector) return empty;
  const { scope } = connector;
  const schedule = scheduleOf(connector);
  const kind = CONNECTOR_KINDS.find((item) => item === connector.kind) ?? "confluence";
  const pageTrees = kind === "confluence" ? storedPageTrees(scope) : [];
  return {
    ...empty,
    key: connector.connector_key,
    kind,
    keys: ((kind === "jira" ? scope.project_keys : scope.spaces) ?? []).join(", "),
    scopeMode: pageTrees.length ? "trees" : "spaces",
    pageTrees,
    jql: scope.jql ?? "",
    knowledgeBases: (scope.knowledge_bases ?? []).join(", "),
    tables: (scope.tables ?? []).filter((table): table is ServiceNowTable => SERVICENOW_TABLES.includes(table as ServiceNowTable)),
    articleQuery: scope.article_query ?? "",
    recordQuery: scope.record_query ?? "",
    products: connector.products.join(", "),
    version: connector.version ?? "",
    limit: String(connector.max_items_per_run),
    state: connector.state,
    scheduleEnabled: schedule.enabled,
    scheduleInterval: String(schedule.interval_minutes),
    releases: kind === "jira" ? scope.releases ?? null : null,
    // A Git repository added from a connection names it at the top level of the listing.
    connectionId: kind === "git_repository" ? repositoryConnectionOf(connector) ?? ""
      : typeof scope.connection_id === "string" ? scope.connection_id : "",
    cluster: kind === "kubernetes" ? scope.cluster ?? "" : "",
    namespaces: kind === "kubernetes" ? (scope.namespaces ?? []).join(", ") : "",
    ...(kind === "git_repository" ? gitFieldsFromScope(scope) : {}),
    ...(kind === REST_KIND ? { rest: restKnowledgeFormOf(scope) } : {}),
  };
}

// Switching the kind of a new connector clears every kind-specific scope field.
export function resetScope(kind: ConnectorKind): Partial<FormState> {
  return { kind, keys: "", scopeMode: "spaces", pageTrees: [], jql: "", knowledgeBases: "", tables: [], articleQuery: "", recordQuery: "", connectionId: "", cluster: "", namespaces: "", rest: emptyRestKnowledgeForm(), ...EMPTY_GIT_FIELDS };
}

function splitKeys(raw: string, transform: (key: string) => string): string[] {
  return Array.from(new Set(raw.split(/[\s,]+/).map((item) => transform(item.trim())).filter(Boolean)));
}

// Why an encoded query could widen or reorder the scope, or null when it can only narrow it.
function encodedQueryProblem(raw: string, label: string): string | null {
  const query = raw.trim();
  if (!query) return null;
  if (query.length > MAX_QUERY_CHARS || CONTROL_CHARS.test(query)) return `The ${label} is at most ${MAX_QUERY_CHARS} characters on one line.`;
  if (query.toLowerCase().includes("javascript:")) return `The ${label} may not contain javascript: values.`;
  const segments = query.split("^");
  const bad = segments.find((segment, index) => !CONDITION.test(segment) && !(index > 0 && OR_CONDITION.test(segment)));
  if (bad === undefined) return null;
  return `The ${label} can only narrow the scope: every ^ part starts with a lowercase field name (or OR and a field `
    + `name after the first part); NQ, EQ, ORDERBY, GROUPBY, RLQUERY, SUBQUERY and empty parts are refused.`;
}

type ScopeResult = { scope: Partial<ConnectorConfig> } | { problem: string };

function servicenowScope(form: FormState): ScopeResult {
  const bases = splitKeys(form.knowledgeBases, (key) => key.toLowerCase());
  if (bases.length > MAX_SCOPE_KEYS) return { problem: `Enter at most ${MAX_SCOPE_KEYS} knowledge bases.` };
  const badBase = bases.find((base) => !SYS_ID.test(base));
  if (badBase) return { problem: `“${badBase}” is not a knowledge base sys_id (32 hexadecimal characters).` };
  const tables = [...form.tables].sort();
  if (!bases.length && !tables.length) return { problem: "Choose at least one knowledge base or record table." };
  const articleQuery = form.articleQuery.trim();
  const recordQuery = form.recordQuery.trim();
  if (articleQuery && !bases.length) return { problem: "An article filter needs at least one knowledge base." };
  if (recordQuery && !tables.length) return { problem: "A record filter needs at least one record table." };
  const problem = encodedQueryProblem(articleQuery, "article filter") ?? encodedQueryProblem(recordQuery, "record filter");
  if (problem) return { problem };
  return {
    scope: { knowledge_bases: bases, tables, article_query: articleQuery || null, record_query: recordQuery || null },
  };
}

function kubernetesScope(form: FormState): ScopeResult {
  const cluster = form.cluster.trim();
  if (!CLUSTER.test(cluster)) {
    return { problem: "Enter the cluster name a Kubernetes connection is bound to (letters, digits and . _ : @ / -)." };
  }
  const namespaces = splitKeys(form.namespaces, (key) => key);
  if (namespaces.length > MAX_NAMESPACES) return { problem: `Enter at most ${MAX_NAMESPACES} namespaces.` };
  const bad = namespaces.find((name) => !NAMESPACE.test(name));
  if (bad) return { problem: `“${bad}” is not a Kubernetes namespace name.` };
  return { scope: { cluster, namespaces } };
}

// The REST fields show each problem at its field; here only whether one blocks the save (the role rule needs the
// operations, which the form checks itself before it submits).
function restScope(form: FormState): ScopeResult {
  const problems = Object.values(restKnowledgeProblems(form.rest, [], true));
  return problems.length ? { problem: problems[0] } : { scope: restKnowledgeBody(form.rest) };
}

function keyedScope(form: FormState): ScopeResult {
  const jira = form.kind === "jira";
  const keys = splitKeys(form.keys, (key) => (jira ? key.toUpperCase() : key));
  // Page trees: whole spaces are optional next to them (none, or ones the trees are not in).
  const trees = !jira && form.scopeMode === "trees";
  if (trees && !keys.length) {
    const problem = pageTreesProblem(form.pageTrees, []);
    return problem ? { problem } : { scope: { spaces: [], page_trees: form.pageTrees } };
  }
  if (!keys.length || keys.length > MAX_SCOPE_KEYS) return { problem: `Enter 1 to ${MAX_SCOPE_KEYS} ${jira ? "project" : "space"} keys.` };
  const badKey = keys.find((key) => !(jira ? PROJECT_KEY : SPACE_KEY).test(key));
  if (badKey && !jira) {
    const fromUrl = spaceKeyFromUrl(badKey);
    if (fromUrl) return { problem: `“${badKey}” is a page address, not a space key. Its space key is ${fromUrl}: enter ${fromUrl}.` };
  }
  if (badKey) return { problem: `“${badKey}” is not a valid ${jira ? "Jira project" : "Confluence space"} key.` };
  if (trees) {
    const problem = pageTreesProblem(form.pageTrees, keys);
    return problem ? { problem } : { scope: { spaces: keys, page_trees: form.pageTrees } };
  }
  if (!jira) return { scope: { spaces: keys } };
  const jql = form.jql.trim();
  if (jql.length > MAX_QUERY_CHARS || ORDER_BY.test(jql)) {
    return { problem: "The JQL filter is at most 500 characters and may not contain ORDER BY (the connector owns the order)." };
  }
  return { scope: { project_keys: keys, jql: jql || null } };
}

export function validate(form: FormState): { config: ConnectorConfig } | { problem: string } {
  if (!CONNECTOR_KEY.test(form.key)) return { problem: "The name must be a short slug: lowercase letters, digits and dashes." };
  const scoped = form.kind === "servicenow" ? servicenowScope(form)
    : form.kind === "git_repository" ? gitRepositoryScope(form)
      : form.kind === "kubernetes" ? kubernetesScope(form)
        : form.kind === REST_KIND ? restScope(form) : keyedScope(form);
  if ("problem" in scoped) return scoped;
  const products = splitProducts(form.products);
  if (products.length > 8 || products.some((product) => !PRODUCT.test(product))) {
    return { problem: "Products are up to 8 lowercase slugs, for example spring-boot." };
  }
  const version = form.version.trim() || null;
  if (version && (!products.length || !VERSION.test(version))) {
    return { problem: "A version needs a product, and is a short version label such as 3.2 or 2024.1." };
  }
  const connectionId = form.connectionId.trim();
  if (connectionId && !CONNECTION_ID.test(connectionId)) {
    return { problem: "The connection id is the id shown on the connection (letters, digits, '-' or '_'), or default." };
  }
  const limit = Number(form.limit);
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) return { problem: "Items per run is a whole number from 1 to 500." };
  const interval = Number(form.scheduleInterval);
  if (!Number.isInteger(interval) || interval < MIN_SCHEDULE_INTERVAL_MINUTES || interval > MAX_SCHEDULE_INTERVAL_MINUTES) {
    return {
      problem: `The schedule interval is a whole number of minutes from ${MIN_SCHEDULE_INTERVAL_MINUTES} to `
        + `${MAX_SCHEDULE_INTERVAL_MINUTES} (7 days).`,
    };
  }
  return {
    config: {
      ...scoped.scope,
      kind: form.kind,
      products,
      version,
      max_items_per_run: limit,
      state: form.state,
      schedule_enabled: form.scheduleEnabled,
      schedule_interval_minutes: interval,
      // The PUT replaces the whole configuration: without the block, saving would switch release sync off.
      ...(form.kind === "jira" ? { releases: form.releases } : {}),
      // Also replaced by every save: an omitted pin would unpin the connector.
      ...(pinnable(form.kind) ? { connection_id: connectionId || null } : {}),
    },
  };
}
