import { useCallback, useEffect, useState } from "react";

import { DataTable, type DataTableColumn } from "../../../layout/DataTable";
import { StatusLabel } from "../../../layout/StatusLabel";
import { AdminHeaderActions } from "../AdminHeaderSlot";
import { listCalls, listDefinitions, loadDefinition, type RestCall, type RestDefinitionListEntry, type RestOperation } from "./restApisApi";
import { callAdmission, callStatus, callsFilterFromSearch, callsQuery, durationText, filterCalls, isRefusedScope, operationOfTool, refusedScopeText } from "./restCallsModel";
import { restErrorView } from "./restErrorsModel";
import { scopeText } from "./restTestCallModel";
import { FormError, Mono } from "./restApisParts";
import "./restApis.css";

const timeText = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "");

function ScopeCell({ call }: { call: RestCall }) {
  const scope = call.scope;
  if (isRefusedScope(scope)) return <span className="rst-text" data-testid="rest-call-refused-scope">{refusedScopeText(scope)}</span>;
  // A scope refusal audited before backend carries no scope; it was not "none".
  if (call.failure_category === "scope_violation") return <span className="rst-muted">Not recorded for this call</span>;
  const limits = Object.keys(scope.params ?? {}).length + Object.keys(scope.body ?? {}).length + (scope.result_filter ? 1 : 0);
  if (!scope.role) return <span className="rst-muted">None applied</span>;
  if (!limits) return <span>{`${scope.role} · no scope`}</span>;
  return (
    <details className="rst-scope-details">
      <summary>{`${scope.role} · ${limits} limit${limits === 1 ? "" : "s"}`}</summary>
      <ul>
        {scopeText(scope).split(" · ").map((line) => <li key={line}>{line}</li>)}
      </ul>
    </details>
  );
}

// Under a write's status, what admitted it (backend): the approval, linked to its detail page, or the
// chat's write plan, linked to the chat where it was decided; a read shows nothing.
function AdmissionCell({ call }: { call: RestCall }) {
  const admission = callAdmission(call);
  if (!admission) return null;
  return (
    <span className="rst-row" data-testid="rest-call-admission">
      <span className="rst-muted">Admitted by</span>
      {admission.href
        ? <a className="ds-link-button" href={admission.href} title={admission.label === "Approval" ? "Open the approval: what was asked and who decided" : "Open the chat where this write plan was decided"}>{admission.linkText}</a>
        : <span className="rst-muted">{admission.label}</span>}
      <span title={admission.id}><Mono>{admission.shortId}</Mono></span>
    </span>
  );
}

// The names come with the call (backend); null means none, or one removed since.
const workspaceName = (call: RestCall) => call.workspace_name ?? (call.workspace_id ? "Removed Workspace" : "No Workspace");

function StatusCell({ call }: { call: RestCall }) {
  const status = callStatus(call);
  return (
    <span className="rst-name">
      <span className="rst-row">
        <StatusLabel label={status.label} tone={status.tone} />
        {status.hint ? <span className="rst-muted">{status.hint}</span> : null}
      </span>
      {call.error ? <span className="rst-call-error" data-testid="rest-call-error">{call.error}</span> : null}
      <AdmissionCell call={call} />
    </span>
  );
}

const CALL_COLUMNS: DataTableColumn<RestCall>[] = [
  {
    key: "time", header: "Time and duration", nowrap: true,
    render: (call) => (
      <span className="rst-name">
        <span>{timeText(call.started_at)}</span>
        <span className="rst-muted">{durationText(call.duration_ms)}</span>
      </span>
    ),
  },
  {
    key: "user", header: "User and Workspace", nowrap: true,
    render: (call) => (
      <span className="rst-name">
        <span>{call.user_name ?? (call.user_id ? "Removed user" : "Unknown")}</span>
        <span className="rst-muted">{workspaceName(call)}</span>
      </span>
    ),
  },
  { key: "operation", header: "Operation", clip: "12rem", render: (call) => <Mono>{operationOfTool(call.tool_name)}</Mono> },
  { key: "status", header: "Status", minWidth: "13rem", render: (call) => <StatusCell call={call} /> },
  { key: "http", header: "HTTP", nowrap: true, align: "end", render: (call) => (call.http_status === null ? "" : String(call.http_status)) },
  {
    key: "records", header: "Kept / dropped", nowrap: true, align: "end",
    render: (call) => (call.status === "succeeded" ? `${call.records} / ${call.dropped_out_of_scope}` : ""),
  },
  { key: "scope", header: "Scope", grow: true, minWidth: "12rem", render: (call) => <ScopeCell call={call} /> },
];

type CallsFilterValue = { definitionId: string; opId: string };

// Admin › Connections › REST APIs › Calls: the latest audited calls (rest_api_call_runs), one row per call, from
// agents and from test calls alike. Every call runs as the connection's technical account; the scope column shows
// the role that allowed it and the limits Octryx applied.
export function RestApiCallsPage() {
  const [calls, setCalls] = useState<RestCall[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [writesOnly, setWritesOnly] = useState(false);
  // API and operation are filtered on the server (backend); a link from an API's detail opens with them set.
  const [filter, setFilter] = useState(() => callsFilterFromSearch(typeof window === "undefined" ? "" : window.location.search));
  const [apis, setApis] = useState<RestDefinitionListEntry[]>([]);
  const [operations, setOperations] = useState<RestOperation[]>([]);
  const shown = filterCalls(calls ?? [], writesOnly);

  const load = useCallback(async () => {
    try {
      setCalls(await listCalls(callsQuery(filter)));
      setError(null);
    } catch (failure) {
      setCalls([]);
      setError(restErrorView(failure).text);
    }
  }, [filter]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { listDefinitions().then(setApis).catch(() => setApis([])); }, []);
  useEffect(() => {
    if (!filter.definitionId) { setOperations([]); return; }
    loadDefinition(filter.definitionId).then((definition) => setOperations(definition.operations ?? [])).catch(() => setOperations([]));
  }, [filter.definitionId]);
  const filtered = Boolean(filter.definitionId);

  return (
    <div className="rst-page" data-testid="rest-calls-page">
      <CallsFilters filter={filter} apis={apis} operations={operations} writesOnly={writesOnly} onWritesOnly={setWritesOnly}
        onFilter={(next) => { setCalls(null); setFilter(next); }} onReload={() => { setCalls(null); void load(); }} />
      <FormError text={error} />
      <DataTable<RestCall>
        label="REST API calls"
        testId="rest-calls-table"
        rows={shown}
        loading={calls === null}
        loadingLabel="calls"
        rowKey={(call) => call.id}
        empty={{
          text: writesOnly && calls?.length ? "No write calls among the latest calls."
            : filtered ? "No calls of this API or operation yet." : "No REST API calls yet. Agents' calls and test calls appear here.",
          testId: "rest-calls-empty",
        }}
        columns={CALL_COLUMNS}
      />
      <p className="rst-muted">Every call runs as the connection's technical account; Octryx decides who may call it. Secrets and answers are never stored here.</p>
    </div>
  );
}

function CallsFilters({ filter, apis, operations, writesOnly, onWritesOnly, onFilter, onReload }: {
  filter: CallsFilterValue;
  apis: RestDefinitionListEntry[];
  operations: RestOperation[];
  writesOnly: boolean;
  onWritesOnly: (next: boolean) => void;
  onFilter: (next: CallsFilterValue) => void;
  onReload: () => void;
}) {
  return (
    <AdminHeaderActions>
      <select className="admin-panel__input rst-filter-select" aria-label="API" value={filter.definitionId} data-testid="rest-calls-api"
        onChange={(event) => onFilter({ definitionId: event.target.value, opId: "" })}>
        <option value="">All APIs</option>
        {apis.map((api) => <option key={api.id} value={api.id}>{api.name}</option>)}
      </select>
      <select className="admin-panel__input rst-filter-select" aria-label="Operation" value={filter.opId} disabled={!filter.definitionId}
        data-testid="rest-calls-operation" onChange={(event) => onFilter({ ...filter, opId: event.target.value })}>
        <option value="">All operations</option>
        {operations.map((op) => <option key={op.id} value={op.id}>{op.llm_name || op.op_key}</option>)}
      </select>
      <label className="admin-panel__checkbox rst-filter">
        <input type="checkbox" checked={writesOnly} onChange={(event) => onWritesOnly(event.target.checked)} data-testid="rest-calls-writes-only" />
        Writes only
      </label>
      <button type="button" className="admin-panel__action-btn" onClick={onReload} data-testid="rest-calls-reload">
        Reload
      </button>
    </AdminHeaderActions>
  );
}
