// Agents & workflows → Agents: Workspace agents and built-ins with their capability ceiling,
// default workflow, scope and use. Opening an agent shows its page (settings, steps, revision, test); built-ins listed for orientation only have no page.
import { useEffect, useMemo, useState, type KeyboardEvent } from "react";

import { Badge, ClassBadge } from "../agentsWorkflows/awBadges";
import "../agentsWorkflows/agentsWorkflows.css";
import "../adminChannels.css";
import {
  EMPTY_OVERVIEW,
  agentRows,
  filterAgentRows,
  readAgentsOverview,
  type AgentRow,
  type AgentsOverview,
  type OverviewAgent,
} from "./agentsOverviewModel";

type ReadJsonFn = <T>(input: RequestInfo, init?: RequestInit) => Promise<T>;

type AgentsOverviewPageProps = {
  ctx: Record<string, unknown>;
};

/** Search, capability filter and "New agent". */
function AgentsToolbar({ query, setQuery, ceiling, setCeiling, onNew }: {
  query: string;
  setQuery: (value: string) => void;
  ceiling: string;
  setCeiling: (value: string) => void;
  onNew: () => void;
}) {
  return (
    <div className="aw-toolbar">
      <input className="admin-users__toolbar-input" value={query} aria-label="Search agents"
        placeholder="Search agents" onChange={(event) => setQuery(event.target.value)} />
      <select className="admin-users__toolbar-select" value={ceiling} aria-label="Capability ceiling"
        onChange={(event) => setCeiling(event.target.value)}>
        <option value="">Any capability</option>
        <option value="read_only">Read-only</option>
        <option value="change">Change</option>
        <option value="deliver">Deliver</option>
      </select>
      <span className="aw-toolbar__spacer" />
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={onNew}>
        New agent
      </button>
    </div>
  );
}

/** Workspace agents open their page by click or Enter; built-in rows have no page. */
function AgentsTable({ rows, usageWindowDays, open, onRowKey }: {
  rows: AgentRow[];
  usageWindowDays: number;
  open: (id: string | null) => void;
  onRowKey: (event: KeyboardEvent, id: string | null) => void;
}) {
  return (
    <table className="admin-panel__table aw-cards aw-table">
      <thead>
        <tr>
          <th>Agent</th><th>Capability ceiling</th><th>Default workflow</th><th>Scope</th>
          <th>{`Used (${usageWindowDays} d)`}</th><th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id ?? `builtin-${row.name}`} tabIndex={row.id ? 0 : -1}
            onClick={() => open(row.id)} onKeyDown={(event) => onRowKey(event, row.id)}
            data-testid={row.id ? `agent-row-${row.id}` : undefined}>
            <td data-l="Agent"><div className="aw-name">{row.name}</div><div className="aw-sub">{row.description}</div></td>
            <td data-l="Ceiling"><ClassBadge value={row.ceiling} /></td>
            <td data-l="Default workflow" className="aw-mono">{row.defaultWorkflow}</td>
            <td data-l="Scope">{row.scope}</td>
            <td data-l="Used">{row.used ?? "–"}</td>
            <td data-l="Status"><Badge kind={row.status[1]}>{row.status[0]}</Badge></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function AgentsOverviewPage({ ctx }: AgentsOverviewPageProps) {
  const { agentBuilderMeta, handleOpenAgentForm, panelAgents, projects, readJson, setSelectedAgentPanelId } =
    ctx as Record<string, any>;
  const [query, setQuery] = useState("");
  const [ceiling, setCeiling] = useState("");
  const [overview, setOverview] = useState<AgentsOverview>(EMPTY_OVERVIEW);
  const agents: OverviewAgent[] = useMemo(() => (Array.isArray(panelAgents) ? panelAgents : []), [panelAgents]);
  const projectOptions = Array.isArray(agentBuilderMeta?.projects) ? agentBuilderMeta.projects : projects || [];

  useEffect(() => {
    const read = readJson as ReadJsonFn | undefined;
    if (!read) return;
    void read<unknown>("/admin/chat/api/panel/agents/overview").then(
      (raw) => setOverview(readAgentsOverview(raw)),
      () => setOverview(EMPTY_OVERVIEW),
    );
  }, [readJson, agents.length]);

  const rows = filterAgentRows(agentRows(agents, overview, projectOptions), query, ceiling);
  const open = (id: string | null) => {
    if (id) setSelectedAgentPanelId(id);
  };
  const onRowKey = (event: KeyboardEvent, id: string | null) => {
    if (event.key === "Enter") open(id);
  };

  return (
    <div className="aw-page" data-testid="agents-overview">
      <AgentsToolbar query={query} setQuery={setQuery} ceiling={ceiling} setCeiling={setCeiling}
        onNew={() => handleOpenAgentForm(null)} />
      {rows.length === 0 ? (
        <div className="admin-panel__empty-state">No agent matches this search.</div>
      ) : (
        <AgentsTable rows={rows} usageWindowDays={overview.usageWindowDays} open={open} onRowKey={onRowKey} />
      )}
      <p className="admin-panel__hint">
        Agents are shared in their Workspace (not per owner). <b>Built-in</b> agents ship with the platform and
        cannot be deleted. An agent never grants permissions: its capability is a <b>ceiling</b>, the workflow
        decides the class, Policies decide what is forbidden.
      </p>
    </div>
  );
}
