import { apiTimeOf } from "./apiTime";
import { ACCESS_MODE_LABEL } from "./connectorTypes";
import { accessModeOf, repositoryConnectionOf, scheduleOf } from "./connectorConfig";
import { formatTime, intervalText } from "./connectorDisplay";
import type { SourceConnector } from "./connectorTypes";
import { gitScopeSummary } from "./gitRepositoryScope";
import { storedPageTrees } from "./confluencePageTree";
import { REST_KIND, restKnowledgeFormOf } from "./rest/restSourceForm";

const WRAP = { overflowWrap: "anywhere" } as const;

function FilterLine({ label, value }: { label: string; value: string | null | undefined }) {
  return value ? <div className="admin-panel__muted" style={WRAP}>{label} <code>{value}</code></div> : null;
}

// A Jira connector's release sync: off (no block), active with its project -> product mapping, or needs configuration.
function ReleaseLine({ connector }: { connector: SourceConnector }) {
  const sync = connector.release_sync;
  if (!sync || sync.state === "off") return null;
  if (sync.state === "needs_configuration") return <div className="admin-panel__muted">Releases: needs configuration (no product mapped)</div>;
  const mapping = Object.entries(sync.products ?? {}).map(([key, product]) => `${key} → ${product}`).join(", ");
  return <div className="admin-panel__muted" style={WRAP}>Releases <code>{mapping}</code></div>;
}

// A Git repository connector: owner/repo at its ref, the connection and access mode when it is read through one, the
// globs, the file limits and the last synced commit.
function GitRepositoryScope({ connector }: { connector: SourceConnector }) {
  const summary = gitScopeSummary(connector.scope);
  const connection = repositoryConnectionOf(connector);
  const mode = accessModeOf(connector);
  return (
    <>
      <div style={WRAP}>Repository <code>{summary.repository || "—"}</code></div>
      {connection ? (
        <div className="admin-panel__muted" style={WRAP} data-testid="scope-connection">
          Connection <code>{connection}</code>{mode ? ` · ${ACCESS_MODE_LABEL[mode]}` : ""}
        </div>
      ) : null}
      <FilterLine label="Ref" value={summary.ref} />
      <FilterLine label="Include" value={summary.include} />
      <FilterLine label="Exclude" value={summary.exclude} />
      {summary.limits ? <div className="admin-panel__muted">{summary.limits}</div> : null}
      <div className="admin-panel__muted" style={WRAP}>{summary.head}</div>
    </>
  );
}

// A Custom REST source: the API and its operations, the role it reads as, the mapping and who finds the items.
function RestScope({ connector }: { connector: SourceConnector }) {
  const form = restKnowledgeFormOf(connector.scope);
  const mapping = Object.entries(form.mapping).filter(([, path]) => path).map(([name, path]) => `${name} ← ${path}`).join(", ");
  return (
    <>
      <div style={WRAP}>API <code>{form.definition}</code> · list <code>{form.operation}</code></div>
      {form.detailOperation ? <FilterLine label="Content from" value={`${form.detailOperation} (${form.detailParam || "its path argument"})`} /> : null}
      {form.contentFrom === "field" ? <FilterLine label="Content field" value={form.contentPath} /> : null}
      <FilterLine label="Read as" value={form.role || null} />
      <FilterLine label="Mapping" value={mapping} />
      <div className="admin-panel__muted">{form.visibility === "workspace" ? "Visible to everyone in the Workspace" : "Restricted by grant"}</div>
    </>
  );
}

// What a connector reads: spaces, projects and JQL, ServiceNow knowledge bases and record tables with filters, or a
// Git repository.
export function ScopeCell({ connector }: { connector: SourceConnector }) {
  const { spaces, project_keys: projects, jql, knowledge_bases: bases, tables } = connector.scope;
  if (connector.kind === "git_repository") return <GitRepositoryScope connector={connector} />;
  if (connector.kind === REST_KIND) return <RestScope connector={connector} />;
  if (connector.kind === "kubernetes") {
    const namespaces = connector.scope.namespaces ?? [];
    return (
      <>
        <div>Cluster <code>{connector.scope.cluster ?? "?"}</code></div>
        <div style={WRAP}>Namespaces {namespaces.length ? <code>{namespaces.join(", ")}</code> : "all the connection may read"}</div>
      </>
    );
  }
  if (connector.kind === "servicenow") {
    return (
      <>
        {bases?.length ? (
          <div style={WRAP}>Knowledge bases <code>{bases.map((base) => base.slice(0, 8)).join(", ")}</code>
            <span className="admin-panel__muted"> ({bases.length})</span></div>
        ) : null}
        <FilterLine label="Article filter" value={connector.scope.article_query} />
        {tables?.length ? <div>Tables <code>{tables.join(", ")}</code></div> : null}
        <FilterLine label="Record filter" value={connector.scope.record_query} />
      </>
    );
  }
  const trees = connector.kind === "confluence" ? storedPageTrees(connector.scope) : [];
  if (spaces || projects || trees.length) {
    const keys = spaces ?? projects ?? [];
    return (
      <>
        {keys.length ? <div>{spaces ? "Spaces" : "Projects"} <code>{keys.join(", ")}</code></div> : null}
        {trees.length ? (
          <div style={WRAP} data-testid="scope-page-trees">
            Page trees <code>{trees.map((tree) => `${tree.space_key} · ${tree.root_page_id}`).join(", ")}</code>
          </div>
        ) : null}
        <FilterLine label="JQL" value={jql} />
        <ReleaseLine connector={connector} />
      </>
    );
  }
  // A kind this UI does not know yet: show its scope keys as they are.
  const entries = Object.entries(connector.scope).filter(([, value]) => value !== null && value !== undefined);
  return <span className="admin-panel__muted" style={WRAP}>{entries.map(([key, value]) => `${key}: ${String(value)}`).join("; ") || "—"}</span>;
}

// The schedule as the server stores it; runs also need the Instance switch, which the listing does not report.
export function ScheduleCell({ connector }: { connector: SourceConnector }) {
  const schedule = scheduleOf(connector);
  if (!schedule.enabled) return <span className="admin-panel__badge admin-panel__badge--inactive">off</span>;
  const paused = connector.state === "paused";
  // Next_run_at is UTC; an unreadable value is never shown as "due now".
  const at = apiTimeOf(schedule.next_run_at);
  const due = schedule.next_run_at ? at !== null && at <= Date.now() : true;
  return (
    <>
      <span className={`admin-panel__badge ${paused ? "admin-panel__badge--warning" : "admin-panel__badge--active"}`}>
        every {intervalText(schedule.interval_minutes)}
      </span>
      <div className="admin-panel__muted">
        {paused ? "no runs while paused" : due ? "next run due now" : at === null ? "next run time not readable" : `next due ${formatTime(schedule.next_run_at)}`}
      </div>
    </>
  );
}
